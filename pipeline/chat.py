"""PC simulator of the Cardputer: same int8 model, retrieval, calculator and turn logic.

  python pipeline/chat.py              # interactive
  python pipeline/chat.py --show-ctx   # also print what the model was shown
Type /new to start a new chat, /quit to exit.
"""
import argparse

import numpy as np

from lib.common import SD_DIR, cfg, load_kb_passages
from lib.fmt import encode_turn_prompt
from lib.kbtext import BM25Index, build_ctx


class Chat:
    """Mirrors firmware/src/chat.c."""

    def __init__(self, engine, index, min_score, seed=0):
        self.e, self.index, self.min_score = engine, index, min_score
        self.rng = np.random.default_rng(seed)
        self.new()

    def new(self):
        self.pos, self.pending = 0, []
        self.e.reset()

    def _feed(self, ids):
        logits = None
        for t in ids:
            logits = self.e.forward(t, self.pos)
            self.pos += 1
        return logits

    def _sample(self, logits):
        if cfg.TEMPERATURE <= 0:
            return int(np.argmax(logits))
        top = np.argsort(-logits)[:cfg.TOP_K]
        p = np.exp((logits[top] - logits[top[0]]) / cfg.TEMPERATURE)
        return int(self.rng.choice(top, p=p / p.sum()))

    def turn(self, user, on_text=print):
        ctx = build_ctx(user, self.index, self.min_score)
        prompt = encode_turn_prompt(self.e.tok.encode, ctx, user)
        if self.pos + len(self.pending) + len(prompt) + cfg.MAX_ANSWER_TOKENS > self.e.ctx_len:
            self.new()  # out of room: forget the history, keep this question
            if 1 + len(prompt) + cfg.MAX_ANSWER_TOKENS > self.e.ctx_len:  # drop the card, keep device + calculator
                ctx = build_ctx(user, None, 0.0)
                prompt = encode_turn_prompt(self.e.tok.encode, ctx, user)
            if 1 + len(prompt) + cfg.MAX_ANSWER_TOKENS > self.e.ctx_len:  # no ctx at all
                ctx = None
                prompt = encode_turn_prompt(self.e.tok.encode, None, user)
                if 1 + len(prompt) + cfg.MAX_ANSWER_TOKENS > self.e.ctx_len:
                    return None, "(message too long)"
        ids = ([self.e.bos] if self.pos == 0 else []) + self.pending + prompt
        self.pending = []
        logits = self._feed(ids)
        out = []
        for _ in range(cfg.MAX_ANSWER_TOKENS):
            t = self._sample(logits)
            if t in (self.e.eot, self.e.eos) or self.pos >= self.e.ctx_len:
                break
            piece = self.e.tok.decode(t)
            out.append(piece)
            on_text(piece)
            logits = self._feed([t])
        self.pending = [self.e.eot]  # fed at the start of the next turn
        return ctx, "".join(out)


def main():
    from lib.npref import Engine
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=str(SD_DIR / "model.bin"))
    ap.add_argument("--show-ctx", action="store_true")
    a = ap.parse_args()
    passages = load_kb_passages()
    chat = Chat(Engine(a.model), BM25Index(passages) if passages else None, cfg.KB_MIN_SCORE)
    print(f"{cfg.CHARACTER_NAME} is ready ({len(passages)} cards). /new = new chat, /quit = exit")
    while True:
        try:
            user = input("\nyou> ").strip()
        except EOFError:
            break
        if user == "/quit":
            break
        if user == "/new":
            chat.new(); print("(new chat)"); continue
        if not user:
            continue
        print(f"{cfg.CHARACTER_NAME}>", end="", flush=True)
        ctx, _ = chat.turn(user, on_text=lambda s: print(s, end="", flush=True))
        print()
        if a.show_ctx:
            print(f"  [ctx] {ctx}")


if __name__ == "__main__":
    main()
