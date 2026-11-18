"""Step 6: tokenize conversations into flat uint16 arrays for training."""
import numpy as np
import sentencepiece as spm

from lib.common import DS_DIR, TOK_DIR, cfg, read_jsonl
from lib.fmt import encode_conversation


def main():
    sp = spm.SentencePieceProcessor(model_file=str(TOK_DIR / "tok.model"))
    enc = lambda s: sp.encode(s)  # noqa: E731
    for split in ("train", "val"):
        convs = read_jsonl(DS_DIR / f"{split}.jsonl")
        ids, lens = [], []
        for c in convs:
            x = encode_conversation(enc, c)
            lens.append(len(x))
            ids.extend(x)
        arr = np.array(ids, dtype=np.uint16)
        arr.tofile(DS_DIR / f"{split}.bin")
        if lens:
            over = sum(1 for n in lens if n > cfg.MAX_SEQ_LEN)
            print(f"{split}: {len(convs)} conversations, {len(arr):,} tokens, "
                  f"mean {np.mean(lens):.0f} / max {max(lens)} tokens per conversation, "
                  f"{over} longer than MAX_SEQ_LEN")


if __name__ == "__main__":
    main()
