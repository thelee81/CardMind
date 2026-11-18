"""Step 4 (device assistant): turn data/generated/device.jsonl into training conversations.

Every user message is replayed through the device's own request matcher (devtext.dev_parse) on
the conversation's simulated status, so each <ctx> holds exactly the Device line the Cardputer
would show, then the calculator line, then the best knowledge card (or the card the
conversation was written from, when search picks a worse one).

A turn is cut (with the rest of its conversation) when:
  - a device conversation's message does not match its planned request (wrong intent or numbers);
  - a card or persona message accidentally triggers an action (the reply never confirmed it);
  - the reply states a number that is not in the ctx, the user's message or an earlier turn.

Output: data/dataset/{train,val}.jsonl and tokenizer_corpus.txt (same format as step 4).
"""
import random
import re
from collections import Counter

from lib import devtext as D
from lib.common import DS_DIR, GEN_DIR, cfg, ensure_dirs, load_kb_passages, read_jsonl, write_jsonl
from lib.kbtext import SCRIPT_MODE, BM25Index, ascii_fold, calc_line
from lib import scripttext as SC

MAX_BOT_WORDS = 60
MAX_USER_WORDS = 50
SWAP_MIN_OVERLAP = 0.2
BAD = re.compile(r"(\*\*|##|^- |\bas an ai\b|\blanguage model\b)", re.I)
NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
STOP = set("""about after again also another because been before being between both could does doing
down each even every from have here into just like made make many more most much must only other over
same should some such than that their them then there these they this those through under until very
want were what when where which while will with would your yours you are and the for not but can its""".split())


def content_words(text):
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3 and w not in STOP}


def overlap(reply, card):
    rw = content_words(reply)
    return len(rw & content_words(card)) / len(rw) if rw and card else 0.0


def numbers(text):
    t = re.sub(r"(?<=\d),(?=\d{3})", "", text)
    t = re.sub(r"\bv(?=\d)", "", t)  # versions: v5.1.4 -> 5.1.4
    t = re.sub(r"0x[0-9a-fA-F]+", lambda m: str(int(m.group(0), 16)), t)  # 0x44 -> 68 (on both sides)
    return {n.lstrip("-") for n in NUM.findall(t)}


def key_value(line):
    """What a reply to this Device line must state (same rule as eval_device.py)."""
    body = line[len("Device: "):]
    for word in ("no SD card", "nothing", "not changed", "not sent", "failed", "no networks", "off"):
        if word in body:
            return word.split()[-1]
    m = re.search(r"set to (\w+)\.", body)
    if m and not m.group(1).isdigit():
        return m.group(1)
    m = re.search(r"address (0x[0-9A-F]+)", body)
    if m:
        return m.group(1)
    nums = NUM.findall(body.replace("ESP32-S3", "").replace("SDA G2, SCL G1", ""))
    return nums[0] if nums else body.split()[0]


RAISED = re.compile(r"\b(raised|increased|turned up|boosted|bumped)\b.{0,40}\b(brightness|backlight|screen)|"
                    r"\b(brightness|backlight|screen)\b.{0,40}\b(raised|increased|turned up|boosted|bumped)", re.I)


SCRIPT_LIMITS = {"100", "200", "2000", "60000", "8000", "255", "600"}  # numbers a limit explanation may state


SCRIPT_REPEAT = 2  # times each script conversation appears in train.jsonl
LONG_WAIT = re.compile(r"wait 60000(?:; wait 60000)+")


def collapse_waits(text):
    """'wait 60000; wait 60000; wait 60000' -> 'repeat 3 { wait 60000 }' (the form the minute hint shows)."""
    return LONG_WAIT.sub(lambda m: "repeat %d { wait 60000 }" % (m.group(0).count("wait")), text)


def script_ok(user, body):
    """(canonical script, None) or (None, reason). Every number in the request must be in the script
    (seconds and minutes may become milliseconds)."""
    prog, err = SC.parse(body.strip())
    if err:
        return None, "invalid"
    text = SC.to_text(prog)
    have = numbers(text)
    for n in numbers(user):
        if n in have:
            continue
        try:
            v = float(n)
        except ValueError:
            return None, "numbers"
        if v == int(v) and (str(int(v * 1000)) in have or str(int(v * 60000)) in have):
            continue
        if 60000 < v * 60000 <= 600000 and "60000" in have:  # minutes over one wait: wait 60000 x N
            continue
        if 0 < v < 60 and v != int(v) and str(round(v * 1000)) in have:  # 0.5 s -> 500 ms
            continue
        return None, "numbers"
    folded = collapse_waits(text)
    if folded != text:
        prog, err = SC.parse(folded)
        if not err:  # depth or node limits could reject it; keep the original then
            text = SC.to_text(prog)
    return text, None


def small_sd_copies(convs, rng):
    """Yield every conversation, plus a copy of SD replies with a small 'used' amount in MB (1 to 999 MB).
    Real cards often hold only the model (a few MB); with few such examples the model mis-copied
    '2 MB used' as '2.8 GB used'. The reply is rewritten by replacing the exact used string."""
    for c in convs:
        yield c
        st = c["status"]
        if c.get("kind") != "device" or not st.get("sd_type"):
            continue
        old = D._size(st["sd_used_mb"])
        text = " ".join(t["bot"] for t in c["turns"]).lower()
        if old == D._size(st["sd_total_mb"]) or old.lower() not in text or re.search(r"full|almost|nearly|low|running out", text):
            continue
        for _ in range(2):
            mb = rng.choice([rng.randint(1, 9), rng.randint(10, 99), rng.randint(100, 999)])
            new = D._size(mb)
            if new in " ".join(t["bot"] for t in c["turns"]):
                continue
            yield dict(c, status=dict(st, sd_used_mb=mb),
                       turns=[dict(t, bot=t["bot"].replace(old, new)) for t in c["turns"]])


def clean(t):
    u, b = ascii_fold(t["user"]), ascii_fold(t["bot"])
    if b.startswith("Device: "):  # the reply copied the ctx prefix
        b = b[8:9].upper() + b[9:]
    if not u or not b or len(b.split()) > MAX_BOT_WORDS or len(u.split()) > MAX_USER_WORDS or BAD.search(b):
        return None
    return u, b


def main():
    ensure_dirs()
    rng = random.Random(cfg.SEED)
    passages = load_kb_passages()
    index = BM25Index(passages)
    print(f"knowledge base: {len(passages)} passages")
    stats, miss = Counter(), Counter()
    convs, seen = [], set()
    for c in small_sd_copies((c for f in sorted(GEN_DIR.glob("device*.jsonl")) for c in read_jsonl(f)),
                             random.Random(cfg.SEED + 5)):
        st = D.DevStatus(**c["status"])
        plan = c.get("plan")
        out, seen_nums = [], set()
        for k, t in enumerate(c["turns"]):
            ct = clean(t)
            if ct is None:
                stats["cut_clean"] += 1
                break
            u, b = ct
            req = D.dev_parse(u)
            if plan:
                if k >= len(plan):
                    stats["cut_extra_turn"] += 1
                    break
                text, example, want = plan[k]
                ok = req.intent == want or (want == D.NONE and req.intent in D.READS)  # a re-read is harmless
                if ok and example:  # actions: same arguments as planned
                    w = D.dev_parse(example)
                    ok = (req.arg, req.ir_addr, req.ir_cmd) == (w.arg, w.ir_addr, w.ir_cmd)
                if not ok:
                    miss[f"{D.NAMES[want]}->{D.NAMES[req.intent]}"] += 1
                    stats["cut_intent"] += 1
                    break
            elif req.intent in D.ACTIONS:
                stats["cut_action_in_qa"] += 1
                break
            is_script = b.startswith(SC.PREFIX)
            if req.script or is_script or c["kind"] == "script":
                # Same rule as the firmware: a script request (req.script) gets ctx "Mode: script." and the
                # reply must be one valid Script line. Refusals are not trained: the interpreter reports limits.
                if not (req.script and is_script):
                    stats["cut_script_mode"] += 1
                    break
                text, why = script_ok(u, b[len(SC.PREFIX):])
                if text is None:
                    stats["cut_script_" + why] += 1
                    break
                stats["turn_script"] += 1
                hints = D.script_hints(u)
                out.append({"ctx": SCRIPT_MODE + (" " + hints if hints else ""), "user": u, "bot": f"{SC.PREFIX} {text}"})
                continue
            dev = None
            if req.intent:
                D.dev_plan(req, st)
                dev = D.dev_line(req, st)
                D.dev_commit(st)
            calc = calc_line(u)
            score, pid = index.search(u)
            card = passages[pid] if pid >= 0 and score >= cfg.KB_MIN_SCORE else None
            src = c.get("card")
            if src and card != src and overlap(b, src) >= SWAP_MIN_OVERLAP and overlap(b, src) > overlap(b, card) + 0.1:
                card = src
                stats["card_swapped"] += 1
            # Same rule as the firmware: with a Device line the card is not shown (it distracts the model).
            # Facts from the card (e.g. "-80 dBm is unusable") may still appear in the reply.
            if dev and c["kind"] == "device":  # fact / persona conversations may ignore a reading
                if key_value(dev).lower() not in b.lower():
                    stats["cut_no_value"] += 1  # the reply must state the reading / result
                    break
                if RAISED.search(b) and "raised" not in dev:
                    stats["cut_false_claim"] += 1  # claims a brightness change the device did not make
                    break
            ctx = " ".join(x for x in (dev, calc, None if dev else card) if x) or None
            allowed = numbers(" ".join(x for x in (ctx or "", u, card or "") if x)) | seen_nums
            bad = numbers(b) - allowed - {str(i) for i in range(11)}  # small counts are fine
            if bad:
                stats["cut_number"] += 1
                if stats["cut_number"] <= 8:
                    print(f"  number {sorted(bad)} not in ctx: {u!r} -> {b[:90]!r}")
                break
            seen_nums |= allowed | numbers(b)
            stats["turn_" + ("device" if dev else "card" if card else "plain")] += 1
            out.append({"ctx": ctx, "user": u, "bot": b})
        if not out:
            stats["conv_dropped"] += 1
            continue
        key = out[0]["user"].lower()
        if key in seen and c["kind"] != "device":  # device turns differ by their readings
            stats["conv_duplicate"] += 1
            continue
        seen.add(key)
        convs.append({"kind": c["kind"], "turns": out})

    rng.shuffle(convs)
    n_val = max(1, int(len(convs) * cfg.VAL_FRACTION)) if len(convs) > 1 else 0
    write_jsonl(DS_DIR / "val.jsonl", convs[:n_val])
    # Scripts are ~13% of the data; showing them twice keeps script accuracy up as device data grows.
    train = convs[n_val:] + [c for c in convs[n_val:] if c["kind"] == "script"] * (SCRIPT_REPEAT - 1)
    rng.shuffle(train)
    write_jsonl(DS_DIR / "train.jsonl", train)
    n_turns = sum(len(c["turns"]) for c in convs)
    print(f"kept {len(convs)} conversations ({n_turns} turns): {dict(Counter(c['kind'] for c in convs))}")
    print("stats:", dict(stats))
    if miss:
        print("matcher misses (planned -> parsed):", dict(miss.most_common(15)))
    with open(DS_DIR / "tokenizer_corpus.txt", "w", encoding="ascii") as f:
        for c in convs:
            for t in c["turns"]:
                for s in (t["ctx"], t["user"], t["bot"]):
                    if s:
                        f.write(s + "\n")
        for p in passages:
            f.write(p + "\n")
    print(f"wrote {DS_DIR}")


if __name__ == "__main__":
    main()
