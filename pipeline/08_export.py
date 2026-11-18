"""Step 8: export the checkpoint + tokenizer to one int8 file: data/sd_card/espllm/model.bin

Layout (little-endian). firmware/src/engine.c and tokenizer.c parse exactly this.

Header, 256 bytes:
  0  "ELM1"          4  u32 version=1
  8  i32 dim         12 i32 hidden_dim   16 i32 n_layers   20 i32 n_heads
  24 i32 n_kv_heads  28 i32 vocab_size   32 i32 max_seq_len 36 f32 rope_theta
  40 i32 group_size (activation quantisation group)
  44 u32 weights_offset  48 u32 tokenizer_offset  52 u32 total_size  56 u32 crc32(bytes 256..end)
  60 i32 bos, eos, ctx, usr, bot, eot
Weights (from weights_offset):
  f32 rms_att[L*dim], f32 rms_ffn[L*dim], f32 rms_final[dim]
  Q tok_emb, then per layer: Q wq, wk, wv, wo, w1, w2, w3
  where Q = f32 scale[rows] + int8 data[rows*cols] (+ zero pad to 4 bytes); w = data * scale[row]
Tokenizer (at tokenizer_offset; offsets below are relative to it):
  "ETK1", u32 vocab, u32 max_token_len, u32 byte_base, u32 n_sorted, u32 n_special, i32 special[n_special]
  f32 score[vocab], u32 str_off[vocab+1], u16 sorted_ids[n_sorted] (+pad), raw piece bytes
"""
import struct
import zlib

import numpy as np
import sentencepiece as spm
import torch

from lib.common import CKPT_DIR, SD_DIR, TOK_DIR, ensure_dirs
from lib.fmt import BOS, BOT, CTX, EOS, EOT, USR

GROUP = 32
N_SPECIAL = 7  # unk, bos, eos, <ctx>, <usr>, <bot>, <eot>


def pad4(b: bytearray):
    while len(b) % 4:
        b.append(0)


def qmat(w: torch.Tensor):
    w = w.detach().float().cpu().numpy()
    scale = np.abs(w).max(axis=1) / 127.0
    scale[scale == 0] = 1.0
    q = np.clip(np.sign(w / scale[:, None]) * np.floor(np.abs(w / scale[:, None]) + 0.5), -127, 127)
    err = np.abs(q * scale[:, None] - w).max()
    out = bytearray(scale.astype("<f4").tobytes()) + bytearray(q.astype(np.int8).tobytes())
    pad4(out)
    return out, err


def tokenizer_blob(sp):
    vocab = sp.get_piece_size()
    pieces, scores, byte_base = [], [], None
    for i in range(vocab):
        p = sp.id_to_piece(i)
        if sp.is_byte(i):
            b = bytes([int(p[3:5], 16)])
            if byte_base is None:
                byte_base = i
        else:
            b = p.replace("▁", " ").encode("utf-8")
        pieces.append(b)
        scores.append(sp.get_score(i))
    assert byte_base is not None and sp.id_to_piece(byte_base) == "<0x00>", "byte_fallback must be on"
    normal = [i for i in range(vocab) if i >= N_SPECIAL and not sp.is_byte(i)]
    sorted_ids = sorted(normal, key=lambda i: pieces[i])
    for a, b in zip(sorted_ids, sorted_ids[1:]):
        assert pieces[a] != pieces[b], f"duplicate piece {pieces[a]!r}"
    head = struct.pack("<4sIIIII", b"ETK1", vocab, max(len(p) for p in pieces), byte_base,
                       len(sorted_ids), N_SPECIAL)
    head += struct.pack(f"<{N_SPECIAL}i", *range(N_SPECIAL))
    blob = bytearray(head)
    blob += struct.pack(f"<{vocab}f", *scores)
    str_off_pos = len(blob)
    blob += b"\0" * 4 * (vocab + 1)
    blob += struct.pack(f"<{len(sorted_ids)}H", *sorted_ids)
    pad4(blob)
    offs = []
    for p in pieces:
        offs.append(len(blob))
        blob += p
    offs.append(len(blob))
    blob[str_off_pos:str_off_pos + 4 * (vocab + 1)] = struct.pack(f"<{vocab + 1}I", *offs)
    pad4(blob)
    return blob


def main():
    ensure_dirs()
    ck = torch.load(CKPT_DIR / "ckpt.pt", map_location="cpu")
    a, sd = ck["args"], ck["model"]
    L, dim, hidden = a["n_layers"], a["dim"], a["hidden_dim"]
    assert dim % GROUP == 0 and hidden % GROUP == 0, "dim and hidden_dim must be multiples of 32"
    assert dim % a["n_heads"] == 0 and a["n_heads"] % a["n_kv_heads"] == 0

    w = bytearray()
    f32 = lambda t: t.detach().float().cpu().numpy().astype("<f4").tobytes()  # noqa: E731
    w += b"".join(f32(sd[f"layers.{l}.attention_norm.weight"]) for l in range(L))
    w += b"".join(f32(sd[f"layers.{l}.ffn_norm.weight"]) for l in range(L))
    w += f32(sd["norm.weight"])
    worst = 0.0
    names = ["attention.wq", "attention.wk", "attention.wv", "attention.wo",
             "feed_forward.w1", "feed_forward.w2", "feed_forward.w3"]
    blob, e = qmat(sd["tok_embeddings.weight"])
    w += blob
    worst = max(worst, e)
    for l in range(L):
        for n in names:
            blob, e = qmat(sd[f"layers.{l}.{n}.weight"])
            w += blob
            worst = max(worst, e)
    pad4(w)

    sp = spm.SentencePieceProcessor(model_file=str(TOK_DIR / "tok.model"))
    assert sp.get_piece_size() == a["vocab_size"]
    tok = tokenizer_blob(sp)

    weights_off = 256
    tok_off = weights_off + len(w)
    total = tok_off + len(tok)
    body = bytes(w) + bytes(tok)
    head = struct.pack("<4sIiiiiiiifiIIII6i", b"ELM1", 1, dim, hidden, L, a["n_heads"], a["n_kv_heads"],
                       a["vocab_size"], a["max_seq_len"], a["rope_theta"], GROUP, weights_off, tok_off,
                       total, zlib.crc32(body), BOS, EOS, CTX, USR, BOT, EOT)
    head = head.ljust(256, b"\0")
    out = SD_DIR / "model.bin"
    out.write_bytes(head + body)
    print(f"wrote {out}: {total / 1e6:.2f} MB (weights {len(w) / 1e6:.2f} MB, tokenizer {len(tok) / 1e3:.0f} KB)")
    print(f"max int8 rounding error {worst:.5f}; crc32 {zlib.crc32(body):08x}")


if __name__ == "__main__":
    main()
