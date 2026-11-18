"""Step 5: train a small SentencePiece BPE tokenizer.

Settings are chosen so the firmware's simple C encoder (greedy highest-score
merges, byte fallback) reproduces SentencePiece exactly; verify.py checks it.
"""
import sentencepiece as spm

from lib.common import DS_DIR, SPECIALS, TOK_DIR, cfg, ensure_dirs


def main():
    ensure_dirs()
    spm.SentencePieceTrainer.train(
        input=str(DS_DIR / "tokenizer_corpus.txt"),
        model_prefix=str(TOK_DIR / "tok"),
        model_type="bpe",
        vocab_size=cfg.VOCAB_SIZE,
        character_coverage=1.0,
        byte_fallback=True,
        split_digits=True,              # every digit is its own token: better arithmetic
        normalization_rule_name="identity",
        remove_extra_whitespaces=False,
        add_dummy_prefix=True,
        user_defined_symbols=SPECIALS,
        unk_id=0, bos_id=1, eos_id=2, pad_id=-1,
        input_sentence_size=2_000_000,
        shuffle_input_sentence=True,
        max_sentence_length=4096,
        num_threads=4,
        minloglevel=1,
    )
    sp = spm.SentencePieceProcessor(model_file=str(TOK_DIR / "tok.model"))
    for i, s in enumerate(SPECIALS):
        assert sp.piece_to_id(s) == 3 + i, f"special {s} got id {sp.piece_to_id(s)}"
    print(f"tokenizer: {sp.get_piece_size()} pieces -> {TOK_DIR / 'tok.model'}")
    print(sp.encode("What is 12 x 7? I think it is 84.", out_type=str))


if __name__ == "__main__":
    main()
