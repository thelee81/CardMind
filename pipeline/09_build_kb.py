"""Step 9: write the SD-card knowledge base: data/sd_card/espllm/kb.bin

Copy the whole data/sd_card/espllm folder to the root of the SD card. It holds
model.bin (copied into flash on first boot) and kb.bin (searched from the card).
"""
from lib.common import SD_DIR, cfg, ensure_dirs, load_kb_passages
from lib.kbtext import BM25Index


def main():
    ensure_dirs()
    passages = load_kb_passages()
    if not passages:
        raise SystemExit("No passages. Run steps 1-2 first.")
    idx = BM25Index(passages)
    out = SD_DIR / "kb.bin"
    idx.write_bin(out, cfg.KB_MIN_SCORE, cfg.KB_BUCKETS)
    print(f"wrote {out}: {len(passages)} passages, {len(idx.postings)} terms, "
          f"{out.stat().st_size / 1e6:.2f} MB")
    for q in ("why do shadows change", "what is 3/4 of 20", "how do i charge the cardputer"):
        s, pid = idx.search(q)
        print(f"  {q!r}: score {s:.2f} -> {passages[pid][:70] + '...' if pid >= 0 else None}")


if __name__ == "__main__":
    main()
