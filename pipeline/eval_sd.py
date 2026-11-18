"""Does the model copy small SD 'used' amounts (MB) correctly? Real cards often hold only a few MB.

  python pipeline/eval_sd.py data/sd_card/espllm/model.bin[,kb.bin] [more models]
"""
import random
import re
import subprocess
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from lib import devtext as D  # noqa: E402
from lib.common import ROOT, SD_DIR  # noqa: E402

HOST = ROOT / "firmware" / "host" / ("host_chat.exe" if sys.platform == "win32" else "host_chat")
QUESTIONS = ["sd card?", "how full is the sd card", "storage?", "is there an sd card", "how much space is used on the sd card"]


def main():
    rng = random.Random(7)
    cases = []
    for i in range(30):
        total = rng.choice([7580, 15193, 30436, 60872])
        used = rng.choice([rng.randint(1, 9), rng.randint(10, 99), rng.randint(100, 999), rng.randint(1024, total)])
        cases.append((QUESTIONS[i % len(QUESTIONS)], total, used))
    for arg in sys.argv[1:] or [str(SD_DIR / "model.bin")]:
        model, _, kb = arg.partition(",")
        lines = []
        for q, total, used in cases:
            lines += [f"/status sd_total_mb={total} sd_used_mb={used}", q, "/new"]
        out = subprocess.run([str(HOST), model, kb or str(SD_DIR / "kb.bin")], input="\n".join(lines + ["/quit"]) + "\n",
                             capture_output=True, text=True, timeout=1200).stdout
        got = re.findall(r"bot> ?(.*?)\n  \[ctx\]", out)
        ok = 0
        bad = []
        for (q, total, used), reply in zip(cases, got):
            want = D._size(used)
            good = want in reply and D._size(total) in reply
            ok += good
            if not good:
                bad.append(f"    used {want}, total {D._size(total)}: {reply[:110]}")
        small = sum(1 for _, _, u in cases if u < 1024)
        print(f"== {arg}\n  SD size copied right {ok}/{len(cases)} ({small} cases under 1 GB)")
        print("\n".join(bad))


if __name__ == "__main__":
    main()
