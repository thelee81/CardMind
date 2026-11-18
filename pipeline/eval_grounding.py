"""Score how well a model uses its <ctx> (calculator line and knowledge card).

Runs fresh questions through the PC build of the device code (firmware/host/host_chat)
and reports, per model:
  calc  - whole-number sums: replies that state the calculator result, or work with the same numbers
  frac  - the same for fractions, mixed numbers, percentages and "of"
  card  - mean share of the reply's content words found in the card it was shown

Each argument is model.bin, or model.bin,kb.bin to use that model's own knowledge base
(default: data/sd_card/espllm/kb.bin).

  python pipeline/eval_grounding.py data/v4/model.bin,data/v4/kb.bin data/sd_card/espllm/model.bin
"""
import importlib.util
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
spec = importlib.util.spec_from_file_location("s4", ROOT / "pipeline" / "04_build_dataset.py")
s4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s4)

HOST = ROOT / "firmware" / "host" / ("host_chat.exe" if sys.platform == "win32" else "host_chat")
KB = ROOT / "data" / "sd_card" / "espllm" / "kb.bin"

CALC_QS = ["what is 23 x 4", "what is 56 + 37", "what is 81 / 9", "what is 140 - 65", "what is 12 x 12",
           "can you work out 305 + 298", "what is 7 x 8", "how much is 45 / 5", "what is 1000 - 357",
           "what is 15 x 6", "what is 250 + 750", "what is 96 / 8", "what is 9 x 9", "what is 432 - 199",
           "what is 25 x 4"]
FRAC_QS = ["what is 3/4 of 20", "what is 2/5 of 35", "what is 1/2 + 1/4", "what is 3/4 + 1/8",
           "what is 2 2/5 + 1 1/5", "what is 11/4 as a mixed number", "what is 6/8 in simplest form",
           "what is 25% of 80", "what is 10% of 50", "what is 5 - 1 3/4", "what is 2/3 of 12",
           "what is 1/2 of 30", "what is 7/10 + 1/10", "what is 3 1/2 x 2", "what is 3/5 + 1/5"]
CARD_QS = ["what is a factor", "what is a right angle", "what is an equivalent fraction",
           "what is the area of a rectangle", "what is a multiple of 6", "what is perimeter",
           "how do i round to the nearest ten", "what is a mixed number", "how do i read a bar graph",
           "what are parallel lines", "how do i find the duration of time", "what is a decimal",
           "what is line symmetry", "how do i draw a bar model", "what are the 8 compass points"]
QS = CALC_QS + FRAC_QS + CARD_QS


def run(arg):
    model, _, kb = arg.partition(",")
    lines = []
    for q in QS:
        lines += [q, "/new"]
    out = subprocess.run([str(HOST), model, kb or str(KB)], input="\n".join(lines + ["/quit"]) + "\n",
                         capture_output=True, text=True, timeout=900).stdout
    replies = re.findall(r"bot> (.*?)\n(?:  \[ctx\] (.*?)\n)?", out)
    assert len(replies) == len(QS), f"parsed {len(replies)} replies"
    return replies


def calc_score(replies):
    calc = {"stated": 0, "same_numbers": 0, "drift": 0}
    for (reply, ctx) in replies:
        m = re.match(r"Calculator: .*?\.(?= |$)", ctx or "")
        how = s4.calc_consistent(m.group(0), reply) if m else None
        calc[how or "drift"] += 1
    return calc


def score(replies):
    nc, nf = len(CALC_QS), len(FRAC_QS)
    calc, frac = calc_score(replies[:nc]), calc_score(replies[nc:nc + nf])
    ov, shown = [], 0
    for (reply, ctx) in replies[nc + nf:]:
        if ctx and ctx != "-":
            shown += 1
            ov.append(s4.overlap(reply, ctx))
    return calc, frac, (sum(ov) / len(ov) if ov else 0.0), shown


def main():
    models = sys.argv[1:] or [str(ROOT / "data" / "sd_card" / "espllm" / "model.bin")]
    for m in models:
        replies = run(m)
        calc, frac, card, shown = score(replies)
        print(f"\n== {m}")
        for name, c, n in (("calc", calc, len(CALC_QS)), ("frac", frac, len(FRAC_QS))):
            print(f"  {name} ({n} q): stated {c['stated']}, same numbers {c['same_numbers']}, drift {c['drift']}")
        print(f"  card ({shown}/{len(CARD_QS)} shown a card): mean overlap {card:.2f}")
        for q, (r, _) in list(zip(QS, replies))[::5]:
            print(f"    {q!r} -> {r[:110]}")


if __name__ == "__main__":
    main()
