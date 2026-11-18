"""NumPy re-implementation of the firmware engine, reading model.bin.

Same int8 weights, same int8 activation groups, same int8 KV cache, same
tokenizer algorithm as firmware/src/{engine,tokenizer}.c. Used by chat.py (a
PC simulator of the device) and verify.py (checks the C build against this).
"""
import struct

import numpy as np


def _round(x):
    return np.sign(x) * np.floor(np.abs(x) + 0.5)  # same as C roundf


class Tokenizer:
    def __init__(self, buf: bytes, off: int):
        magic, self.vocab, self.max_len, self.byte_base, n_sorted, n_special = struct.unpack_from("<4sIIIII", buf, off)
        assert magic == b"ETK1"
        p = off + 24
        self.special = set(struct.unpack_from(f"<{n_special}i", buf, p)); p += 4 * n_special
        self.scores = np.frombuffer(buf, "<f4", self.vocab, p); p += 4 * self.vocab
        offs = struct.unpack_from(f"<{self.vocab + 1}I", buf, p); p += 4 * (self.vocab + 1)
        self.pieces = [bytes(buf[off + offs[i]:off + offs[i + 1]]) for i in range(self.vocab)]
        sorted_ids = struct.unpack_from(f"<{n_sorted}H", buf, p)
        self.lookup = {self.pieces[i]: i for i in sorted_ids}

    def encode(self, text: str):
        data = (" " + text).encode("ascii", "replace")
        ids = []
        for b in data:
            ids.append(self.lookup.get(bytes([b]), self.byte_base + b))
        while True:
            best, best_i, best_id = -1e30, -1, -1
            for i in range(len(ids) - 1):
                tid = self.lookup.get(self.pieces[ids[i]] + self.pieces[ids[i + 1]])
                if tid is not None and self.scores[tid] > best:
                    best, best_i, best_id = self.scores[tid], i, tid
            if best_i < 0:
                return ids
            ids[best_i:best_i + 2] = [best_id]

    def decode(self, tid: int) -> str:
        if tid in self.special:
            return ""
        return self.pieces[tid].decode("ascii", "replace")


class QMat:
    def __init__(self, buf, p, rows, cols):
        self.scale = np.frombuffer(buf, "<f4", rows, p).astype(np.float32)
        q = np.frombuffer(buf, np.int8, rows * cols, p + 4 * rows).reshape(rows, cols)
        self.q = q.astype(np.int32)
        self.rows, self.cols = rows, cols
        n = 4 * rows + rows * cols
        self.end = p + n + (-n % 4)

    def row(self, i):
        return self.q[i].astype(np.float32) * self.scale[i]


class Engine:
    def __init__(self, path, ctx_len=None):
        buf = open(path, "rb").read()
        (magic, ver, self.dim, self.hidden, self.L, self.H, self.KVH, self.vocab, self.max_seq,
         self.theta, self.G, w_off, t_off, total, crc) = struct.unpack_from("<4sIiiiiiiifiIIII", buf, 0)
        assert magic == b"ELM1" and ver == 1
        self.bos, self.eos, self.ctx_id, self.usr, self.bot, self.eot = struct.unpack_from("<6i", buf, 60)
        self.hd = self.dim // self.H
        self.kvd = self.KVH * self.hd
        p = w_off
        f = lambda n: np.frombuffer(buf, "<f4", n, p).astype(np.float32)  # noqa: E731
        self.rms_att = f(self.L * self.dim).reshape(self.L, self.dim); p += 4 * self.L * self.dim
        self.rms_ffn = f(self.L * self.dim).reshape(self.L, self.dim); p += 4 * self.L * self.dim
        self.rms_final = f(self.dim); p += 4 * self.dim
        self.emb = QMat(buf, p, self.vocab, self.dim); p = self.emb.end
        self.layers = []
        shapes = [(self.dim, self.dim), (self.kvd, self.dim), (self.kvd, self.dim), (self.dim, self.dim),
                  (self.hidden, self.dim), (self.dim, self.hidden), (self.hidden, self.dim)]
        for _ in range(self.L):
            mats = []
            for r, c in shapes:
                m = QMat(buf, p, r, c); p = m.end
                mats.append(m)
            self.layers.append(mats)
        self.tok = Tokenizer(buf, t_off)
        self.ctx_len = min(ctx_len or self.max_seq, self.max_seq)
        self.reset()

    def reset(self):
        n = self.ctx_len
        self.kq = np.zeros((self.L, n, self.KVH, self.hd), np.int32)
        self.vq = np.zeros((self.L, n, self.KVH, self.hd), np.int32)
        self.ks = np.zeros((self.L, n, self.KVH), np.float32)
        self.vs = np.zeros((self.L, n, self.KVH), np.float32)

    # ---- math kernels (mirror engine.c)
    def _quant_act(self, x):
        g = x.reshape(-1, self.G)
        s = (np.abs(g).max(axis=1) / 127.0).astype(np.float32)
        s[s == 0] = 1.0
        q = np.clip(_round(g / s[:, None]), -127, 127).astype(np.int32)
        return q, s

    def _matmul(self, m: QMat, x):
        q, s = self._quant_act(x)
        part = (m.q.reshape(m.rows, -1, self.G) * q[None]).sum(axis=2)  # (rows, groups) int
        return ((part.astype(np.float32) * s[None]).sum(axis=1) * m.scale).astype(np.float32)

    @staticmethod
    def _rms(x, w):
        return (x / np.sqrt(np.mean(x * x) + 1e-5) * w).astype(np.float32)

    def _rope(self, v, pos):
        v = v.reshape(-1, self.hd // 2, 2)
        i = np.arange(self.hd // 2, dtype=np.float32)
        ang = pos * np.power(np.float32(self.theta), -2.0 * i / self.hd).astype(np.float32)
        c, s = np.cos(ang).astype(np.float32), np.sin(ang).astype(np.float32)
        x0, x1 = v[..., 0].copy(), v[..., 1].copy()
        v[..., 0] = x0 * c - x1 * s
        v[..., 1] = x0 * s + x1 * c
        return v.reshape(-1)

    def forward(self, token, pos):
        x = self.emb.row(token)
        for l, (wq, wk, wv, wo, w1, w2, w3) in enumerate(self.layers):
            xb = self._rms(x, self.rms_att[l])
            q = self._rope(self._matmul(wq, xb), pos)
            k = self._rope(self._matmul(wk, xb), pos).reshape(self.KVH, self.hd)
            v = self._matmul(wv, xb).reshape(self.KVH, self.hd)
            for kv, (tq, ts) in ((k, (self.kq, self.ks)), (v, (self.vq, self.vs))):
                sc = (np.abs(kv).max(axis=1) / 127.0).astype(np.float32)
                sc[sc == 0] = 1.0
                tq[l, pos] = np.clip(_round(kv / sc[:, None]), -127, 127)
                ts[l, pos] = sc
            out = np.zeros(self.dim, np.float32)
            rep = self.H // self.KVH
            for h in range(self.H):
                kh = h // rep
                qh = q[h * self.hd:(h + 1) * self.hd]
                kk = self.kq[l, :pos + 1, kh].astype(np.float32) * self.ks[l, :pos + 1, kh, None]
                att = kk @ qh / np.sqrt(np.float32(self.hd))
                att = np.exp(att - att.max())
                att /= att.sum()
                vv = self.vq[l, :pos + 1, kh].astype(np.float32) * self.vs[l, :pos + 1, kh, None]
                out[h * self.hd:(h + 1) * self.hd] = att @ vv
            x = x + self._matmul(wo, out)
            xb = self._rms(x, self.rms_ffn[l])
            h1, h3 = self._matmul(w1, xb), self._matmul(w3, xb)
            hb = (h1 / (1 + np.exp(-h1)) * h3).astype(np.float32)
            x = x + self._matmul(w2, hb)
        return self._matmul(self.emb, self._rms(x, self.rms_final))
