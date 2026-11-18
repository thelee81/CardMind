"""Step 7: train the model on the packed token files.

  python pipeline/07_train.py            # uses config.py
  python pipeline/07_train.py --resume   # continue from data/ckpt/ckpt.pt

A CUDA build of PyTorch makes this minutes instead of hours.
"""
import argparse
import math
import time
from dataclasses import asdict

import numpy as np
import torch

from lib.common import CKPT_DIR, DS_DIR, cfg, ensure_dirs
from lib.model import ModelArgs, Transformer


def get_batch(data, bs, T, device):
    ix = np.random.randint(0, len(data) - T - 1, size=bs)
    x = np.stack([data[i:i + T] for i in ix]).astype(np.int64)
    y = np.stack([data[i + 1:i + 1 + T] for i in ix]).astype(np.int64)
    return torch.from_numpy(x).to(device), torch.from_numpy(y).to(device)


def lr_at(it):
    if it < cfg.WARMUP_ITERS:
        return cfg.LEARNING_RATE * (it + 1) / cfg.WARMUP_ITERS
    r = min(1.0, (it - cfg.WARMUP_ITERS) / max(1, cfg.MAX_ITERS - cfg.WARMUP_ITERS))
    return cfg.MIN_LR + 0.5 * (1 + math.cos(math.pi * r)) * (cfg.LEARNING_RATE - cfg.MIN_LR)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()
    ensure_dirs()
    device = ("cuda" if torch.cuda.is_available() else "cpu") if cfg.DEVICE == "auto" else cfg.DEVICE
    torch.manual_seed(cfg.SEED)
    np.random.seed(cfg.SEED)

    train = np.fromfile(DS_DIR / "train.bin", dtype=np.uint16)
    val = np.fromfile(DS_DIR / "val.bin", dtype=np.uint16)
    T = min(cfg.MAX_SEQ_LEN, len(val) - 2, len(train) - 2)
    if T < 32:
        raise SystemExit("Not enough data to train. Did steps 3-6 run?")
    print(f"device {device}; train {len(train):,} tokens, val {len(val):,} tokens, seq {T}")

    args = ModelArgs(dim=cfg.DIM, n_layers=cfg.N_LAYERS, n_heads=cfg.N_HEADS, n_kv_heads=cfg.N_KV_HEADS,
                     hidden_dim=cfg.HIDDEN_DIM, vocab_size=cfg.VOCAB_SIZE, max_seq_len=cfg.MAX_SEQ_LEN,
                     rope_theta=cfg.ROPE_THETA, dropout=cfg.DROPOUT)
    model = Transformer(args).to(device)
    print(f"model: {model.n_params() / 1e6:.2f}M parameters")
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.LEARNING_RATE, betas=(0.9, 0.95),
                            weight_decay=cfg.WEIGHT_DECAY)
    start, best = 0, float("inf")
    ckpt_path = CKPT_DIR / "ckpt.pt"
    if a.resume and ckpt_path.exists():
        ck = torch.load(ckpt_path, map_location=device)
        model.load_state_dict(ck["model"])
        opt.load_state_dict(ck["opt"])
        start, best = ck["iter"] + 1, ck["best_val"]
        print(f"resumed at iter {start}, best val {best:.3f}")

    use_amp = device == "cuda"

    @torch.no_grad()
    def evaluate():
        model.eval()
        out = {}
        for name, d in (("train", train), ("val", val)):
            losses = []
            for _ in range(cfg.EVAL_ITERS):
                x, y = get_batch(d, cfg.BATCH_SIZE, T, device)
                with torch.autocast(device, dtype=torch.bfloat16, enabled=use_amp):
                    _, loss = model(x, y)
                losses.append(loss.item())
            out[name] = float(np.mean(losses))
        model.train()
        return out

    t0 = time.time()
    for it in range(start, cfg.MAX_ITERS):
        for g in opt.param_groups:
            g["lr"] = lr_at(it)
        if it % cfg.EVAL_INTERVAL == 0 or it == cfg.MAX_ITERS - 1:
            ev = evaluate()
            print(f"iter {it}: train {ev['train']:.3f}  val {ev['val']:.3f}  ({time.time() - t0:.0f}s)")
            if ev["val"] < best:
                best = ev["val"]
                torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "args": asdict(args),
                            "iter": it, "best_val": best}, ckpt_path)
        x, y = get_batch(train, cfg.BATCH_SIZE, T, device)
        with torch.autocast(device, dtype=torch.bfloat16, enabled=use_amp):
            _, loss = model(x, y)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.GRAD_CLIP)
        opt.step()
    print(f"done. best val loss {best:.3f} -> {ckpt_path}")


if __name__ == "__main__":
    main()
