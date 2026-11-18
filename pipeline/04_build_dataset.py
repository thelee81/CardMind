"""Step 4: clean the conversations and attach the device-style <ctx> to every turn.

For each child message we run the *same* calculator and BM25 retrieval the
firmware runs, then ground the turn (see SWAP_MIN_OVERLAP etc. below) so the
model learns to use the card and the calculator result it is shown.

Output: data/dataset/{train,val}.jsonl and data/dataset/tokenizer_corpus.txt
"""
import random
import re

from lib.common import CONVERSATIONS, DS_DIR, cfg, ensure_dirs, load_kb_passages, read_jsonl, write_jsonl
from lib.kbtext import BM25Index, ascii_fold, calc_line

# Grounding: teach the model to USE the <ctx>. The card a conversation was written from replaces
# a worse retrieval; replies that skip the calculator result are cut; and only a small share of
# card/reply mismatches is kept (so the model still learns to ignore a bad retrieval).
SWAP_MIN_OVERLAP = 0.25      # reply must share this much with the source card to swap it in
LOW_OVERLAP = 0.15           # below this, the reply ignores the card
KEEP_MISMATCH = 0.10         # share of low-overlap card turns kept as "ignore it" examples
STATE_RESULT_FIRST = True    # prefix "3/4 of 20 = 15." to calculator turns that never state the result
STOP = set("""about above after again also always another because been before being below between
both could does doing down during each even every from have having here into just like made make
many more most much must only other over same should some such than that their them then there
these they this those through under until very want were what when where which while will with
would your yours yourself you are and the for not but can its it's lets let's great good nice
well done brilliant awesome super wow yes""".split())


def content_words(text):
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) >= 4 and w not in STOP}


def overlap(reply, card):
    """Share of the reply's content words that appear in the card."""
    rw = content_words(reply)
    return len(rw & content_words(card)) / len(rw) if rw and card else 0.0


def _has_num(text, num):
    return re.search(r"(?<![\d.])" + re.escape(num) + r"(?![\d]|\.\d)", text) is not None


def _has_result(text, res):
    """Like _has_num, but a result is not found inside a fraction ("3" in "3/4", "1/4" in "2 1/4")."""
    lead = r"(?<![\d./])(?<!\d )" if "/" in res else r"(?<![\d./])"
    return re.search(lead + re.escape(res) + r"(?![\d]|\.\d|/\d| \d+/)", text) is not None


CALC_RE = re.compile(r"Calculator: ([^=]*) = (.*?)(?: \(or ([^)]*)\))?\.$")
_ANS = r"(-?\d+(?:\.\d+)?(?: \d+/\d+|/\d+)?)"


def states_wrong(text, expr, res, alt):
    """True if the reply writes the question's sum with a different answer ("9 x 9 = 36")."""
    pat = r"\s*".join(re.escape(p) for p in expr.split())
    pat = pat.replace(r"\s*x\s*", r"\s*(?:x|times|\*)\s*")
    for m in re.finditer(r"(?<![\d./])" + pat + r"\s*(?:=|is|equals|makes|gives)\s*" + _ANS, text):
        got = m.group(1)
        if got != res and got != alt and not (alt and alt.startswith(got + " remainder")):
            return True
    return False


def calc_consistent(line, reply):
    """Keep the turn if the reply states the calculator's result, or (teaching step by step)
    works with the same numbers as the question. Cut it if it drifts to other numbers or
    writes the sum with a wrong answer."""
    expr, res, alt = CALC_RE.match(line).groups()
    text = re.sub(r"(?<=\d),(?=\d{3})", "", reply)  # 1,000 -> 1000
    text = re.sub(r"(\d) and (\d+/\d+)", r"\1 \2", text)  # "2 and 3/4" -> "2 3/4"
    if states_wrong(text, expr, res, alt):
        return None
    if _has_result(text, res) or (alt and "remainder" not in alt and _has_result(text, alt)):
        return "stated"
    if all(_has_num(text, n) for n in re.findall(r"\d+(?:\.\d+)?", expr)):
        return "same_numbers"
    return None

MAX_BOT_WORDS = 70
MAX_USER_WORDS = 60
BAD = re.compile(r"(\*\*|##|^- |\bas an ai\b|\blanguage model\b)", re.I)


def clean_turn(t):
    u, b = ascii_fold(t["user"]), ascii_fold(t["bot"])
    if not u or not b or len(b.split()) > MAX_BOT_WORDS or len(u.split()) > MAX_USER_WORDS:
        return None
    if BAD.search(b):
        return None
    return u, b


def main():
    ensure_dirs()
    rng = random.Random(cfg.SEED)
    passages = load_kb_passages()
    index = BM25Index(passages) if passages else None
    print(f"knowledge base: {len(passages)} passages")

    convs, seen, dropped = [], set(), 0
    kept_cards = set(passages)
    stats = {k: 0 for k in ("off_subject", "result_prefixed", "calc_stated", "calc_same_numbers", "calc_cut", "swapped", "grounded", "mismatch_kept", "mismatch_dropped")}
    for c in (c for f in sorted(CONVERSATIONS.parent.glob("conversations*.jsonl")) for c in read_jsonl(f)):
        if c.get("kind") == "curriculum" and c.get("card") not in kept_cards:
            stats["off_subject"] += 1  # written from a card of a subject not in cfg.SUBJECTS
            continue
        turns = []
        for t in c["turns"]:
            ct = clean_turn(t)
            if ct is None:
                break  # keep the clean prefix of the conversation
            turns.append(ct)
        if not turns:
            dropped += 1
            continue
        key = turns[0][0].lower()
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        source = c.get("card")  # same raw text as index.passages
        out = []
        for u, b in turns:
            calc = calc_line(u)
            if calc:
                how = calc_consistent(calc, b)
                if how is None:
                    stats["calc_cut"] += 1
                    break  # Bolt drifted to other numbers: keep only the turns before
                stats["calc_" + how] += 1
                if how == "same_numbers" and STATE_RESULT_FIRST:
                    # teaches step by step but never says the answer: say it first, as round 2 does
                    expr, res, _ = CALC_RE.match(calc).groups()
                    b2 = f"{expr} = {res}. {b}"
                    if len(b2.split()) <= MAX_BOT_WORDS:
                        b = b2
                        stats["result_prefixed"] += 1
            card = None
            if index is not None:
                score, pid = index.search(u)
                if pid >= 0 and score >= cfg.KB_MIN_SCORE:
                    card = index.passages[pid]
            if source and card != source:
                o_src, o_ret = overlap(b, source), overlap(b, card)
                if o_src >= SWAP_MIN_OVERLAP and o_src > o_ret + 0.1:
                    card = source
                    stats["swapped"] += 1
            if card:
                if overlap(b, card) < LOW_OVERLAP:
                    if rng.random() < KEEP_MISMATCH:
                        stats["mismatch_kept"] += 1
                    else:
                        card = None
                        stats["mismatch_dropped"] += 1
                else:
                    stats["grounded"] += 1
            parts = [x for x in (calc, card) if x]
            out.append({"ctx": " ".join(parts) if parts else None, "user": u, "bot": b})
        if not out:
            dropped += 1
            continue
        convs.append({"kind": c.get("kind", "?"), "turns": out})

    rng.shuffle(convs)
    n_val = max(1, int(len(convs) * cfg.VAL_FRACTION)) if len(convs) > 1 else 0
    write_jsonl(DS_DIR / "val.jsonl", convs[:n_val])
    write_jsonl(DS_DIR / "train.jsonl", convs[n_val:])

    with_ctx = sum(1 for c in convs for t in c["turns"] if t["ctx"])
    n_turns = sum(len(c["turns"]) for c in convs)
    print(f"kept {len(convs)} conversations ({n_turns} turns, {with_ctx} with ctx), dropped {dropped}")
    print("grounding:", stats)

    with open(DS_DIR / "tokenizer_corpus.txt", "w", encoding="ascii") as f:
        for c in convs:
            for t in c["turns"]:
                for s in (t["ctx"], t["user"], t["bot"]):
                    if s:
                        f.write(s + "\n")
        for p in passages:  # the model reads every passage on device, so the tokenizer should know them
            f.write(p + "\n")
    print(f"wrote {DS_DIR}")


if __name__ == "__main__":
    main()
