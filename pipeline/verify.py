"""Check that the C code (built for the PC) matches the Python pipeline exactly.

  sh firmware/host/build_host.sh
  python pipeline/verify.py

Checks: tokenizer (SentencePiece vs Python mirror vs C), calculator, knowledge-base
search, and logits (PyTorch float vs NumPy int8 mirror vs C int8).
"""
import random
import subprocess
import sys

import numpy as np
import sentencepiece as spm

from lib.common import CKPT_DIR, DS_DIR, ROOT, SD_DIR, TOK_DIR, cfg, load_kb_passages, read_jsonl
from lib.devtext import dev_line, dev_parse, dev_plan, example_status
from lib.kbtext import BM25Index, calc_line
from lib.scripttext import check as script_check
from lib.npref import Engine

HOST = ROOT / "firmware" / "host" / ("host_chat.exe" if sys.platform == "win32" else "host_chat")
CALC_CASES = [
    "what is 12 x 7", "12x7?", "17 divided by 5", "3 + 4 x 5 - 6 / 2", "1,250 plus 3,750", "2.5 times 4",
    "what is 100 take away 37", "9 / 0", "no maths here", "I have 3 apples and 4 pears", "7 multiplied by 8 is?",
    "0.1 + 0.2", "1000000 x 1000000", "15 / 4", "5 - 9", "12, 345 + 1", "12,345 + 1", "3 x 4 x 5",
    # fractions, mixed numbers, percentages, "of"
    "what is 3/4 of 20", "2 2/5 + 1 1/5", "what is 2 2/5", "25% of 80", "15 percent of 30", "3/4 + 1/8",
    "11/4", "6/8", "3/4", "1/3", "1/3 of 10", "2 1/2 - 3 3/4", "1/2 + 0.25", "1 2/3 divided by 1/3",
    "2/0", "50% of 3/4", "12 3/4 + 7 3/8 - 2 1/16", "999999999999/7 x 999999", "is 3/4 bigger than 2/3",
]
SCRIPT_CASES = [
    "repeat 5 { led red; wait 300; led off; wait 300 }", "if battery < 20 { beep 1000 500 } else { show battery }",
    "repeat 6 { show mic; wait 10000 }", "if mic < -40 { beep }", "ir 0x20 0x10; wait 200; ir 0x20 0x10",
    "repeat 100 { repeat 100 { beep } }", "repeat 3 { led blue", "led purple; bright 5", "foo", "", "led red;; beep",
    "repeat 2 { repeat 2 { repeat 2 { repeat 2 { beep } } } }", "wait 60000; wait 60000; wait 60000", "BEEP 440",
]
DEV_CASES = [
    "battery?", "battery status", "how hot is the chip", "free ram", "is there an sd card", "how noisy is it",
    "scan wifi", "what is on the grove port", "uptime", "screen brightness?", "vol?", "what chip is this",
    "status report", "turn the led red", "led off", "how do i turn the led red in arduino", "is the led on",
    "dim the screen", "set brightness to 40", "volume 30", "mute", "louder", "beep", "test sound please",
    "send ir address 4 command 8", "send ir 0x20", "send ir address 300 command 1", "hello", "what can you do",
    "blink the led red 5 times", "beep every 10 seconds", "if the battery is low then beep", "how many minutes since boot",
]
fails = 0


def check(name, ok, detail=""):
    global fails
    print(f"[{'ok' if ok else 'FAIL'}] {name} {detail}")
    fails += 0 if ok else 1


def host(*args):
    return subprocess.run([str(HOST), *map(str, args)], capture_output=True, text=True, check=True).stdout.strip()


def main():
    rng = random.Random(0)
    eng = Engine(SD_DIR / "model.bin")
    sp = spm.SentencePieceProcessor(model_file=str(TOK_DIR / "tok.model"))
    texts = [t["user"] for c in read_jsonl(DS_DIR / "val.jsonl") for t in c["turns"]]
    texts += [t["bot"] for c in read_jsonl(DS_DIR / "val.jsonl") for t in c["turns"]]
    texts += load_kb_passages() + ["what is 12 x 7?", "  two  spaces ", "weird ~ chars {}|"]
    rng.shuffle(texts)

    bad = [t for t in texts[:300] if sp.encode(t) != eng.tok.encode(t)]
    check("tokenizer: SentencePiece == python mirror", not bad, f"({len(bad)} mismatches of {min(300, len(texts))})"
          + (f" e.g. {bad[0]!r}" if bad else ""))

    have_host = HOST.exists()
    if not have_host:
        print(f"(no {HOST.name}; run sh firmware/host/build_host.sh to check the C code)")
    else:
        bad = [t for t in texts[:40] if host("--tok", SD_DIR / "model.bin", t) != " ".join(map(str, sp.encode(t)))]
        check("tokenizer: SentencePiece == C", not bad, f"({len(bad)} mismatches of {min(40, len(texts))})")
        bad = [(c, calc_line(c), host("--calc", c)) for c in CALC_CASES if (calc_line(c) or "NONE") != host("--calc", c)]
        check("calculator: python == C", not bad, str(bad[:2]) if bad else "")
        dev_texts = DEV_CASES + [t for t in texts[:200]]
        bad = []
        for q in dev_texts:
            r = dev_parse(q)
            st = example_status()
            dev_plan(r, st)
            want = f"{r.intent} {r.script} {dev_line(r, st) or 'NONE'}"
            if host("--dev", q) != want:
                bad.append((q, want))
        check("device requests: python == C", not bad, f"({len(bad)} of {len(dev_texts)})" + (f" e.g. {bad[0]}" if bad else ""))
        bad = [(q, script_check(q)) for q in SCRIPT_CASES if host("--script", q) != script_check(q)]
        from lib.devtext import script_hints
        hq = [q for q, _ in __import__("eval_scripts").CASES] + [t for t in texts[:100]]
        bad = [(q, script_hints(q)) for q in hq if host("--hints", q) != script_hints(q)]
        check("script hints: python == C", not bad, f"({len(bad)} of {len(hq)})" + (f" e.g. {bad[0]}" if bad else ""))
        bad = [(q, script_check(q)) for q in SCRIPT_CASES if host("--script", q) != script_check(q)]
        check("card scripts: python == C", not bad, f"({len(bad)} of {len(SCRIPT_CASES)})" + (f" e.g. {bad[0]}" if bad else ""))
        kbfile = SD_DIR / "kb.bin"
        passages = load_kb_passages()
        if kbfile.exists() and passages:
            idx = BM25Index(passages)
            qs = [t[:200] for t in texts[:60]]  # device input is at most 200 chars (INPUT_MAX_CHARS)
            bad = []
            for q in qs:
                s, pid = idx.search(q)
                cid, cs = host("--kb", kbfile, q).split()
                if int(cid) != pid or abs(float(cs) - s) > 1e-3 * max(1, s):
                    bad.append((q, pid, s, cid, cs))
            check("kb search: python == C", not bad, f"({len(bad)} of {len(qs)})" + (f" e.g. {bad[0]}" if bad else ""))

    ids = [eng.bos] + sp.encode("what is 12 x 7?")[:20] + [eng.bot]
    ref = None
    for p, t in enumerate(ids):
        ref = eng.forward(t, p)
    if have_host:
        c = np.array([float(v) for v in host("--logits", SD_DIR / "model.bin", *ids).split()])
        d = np.abs(c - ref).max()
        check("logits: numpy int8 == C int8", d < 2e-2 * max(1.0, np.abs(ref).max()) and c.argmax() == ref.argmax(),
              f"(max abs diff {d:.2e}, argmax {c.argmax()} vs {ref.argmax()})")
    try:
        import torch
        from lib.model import ModelArgs, Transformer
        ck = torch.load(CKPT_DIR / "ckpt.pt", map_location="cpu")
        m = Transformer(ModelArgs(**ck["args"]))
        m.load_state_dict(ck["model"])
        m.eval()
        with torch.no_grad():
            fl = m(torch.tensor([ids]))[0][0, -1].numpy()
        pf = np.exp(fl - fl.max()); pf /= pf.sum()
        pq = np.exp(ref - ref.max()); pq /= pq.sum()
        print(f"[info] float vs int8: top-1 {'same' if fl.argmax() == ref.argmax() else 'differs'}, "
              f"KL {float(np.sum(pf * (np.log(pf + 1e-12) - np.log(pq + 1e-12)))):.4f}")
    except FileNotFoundError:
        pass
    print("ALL CHECKS PASSED" if not fails else f"{fails} CHECK(S) FAILED")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
