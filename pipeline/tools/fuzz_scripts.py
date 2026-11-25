"""Fuzz the Card script parser: Python (scripttext.check) must equal C (host_chat --script).

  python pipeline/tools/fuzz_scripts.py [N]      (build firmware/host first)
"""
import pathlib
import random
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lib import scripttext as S  # noqa: E402

HOST = pathlib.Path(__file__).resolve().parents[2] / "firmware" / "host" / "host_chat.exe"
WORDS = (["led", "bright", "vol", "beep", "ir", "wait", "show", "repeat", "if", "else", "sound", "face"] + S.COLORS
         + S.READINGS + S.SOUNDS + S.FACES + ["moo", "x", "ledd"])
SYMS = ["{", "}", ";", "<", ">", "<=", ">=", "==", "!=", "!", "="]


def piece(rng):
    r = rng.random()
    if r < 0.55:
        return rng.choice(WORDS).upper() if rng.random() < 0.05 else rng.choice(WORDS)
    if r < 0.8:
        return str(rng.choice([0, 1, 5, 10, 99, 100, 101, 255, 256, 300, 2000, 8000, 60000, 60001, -5, rng.randint(-2000, 70000)]))
    if r < 0.85:
        return "0x%x" % rng.randint(0, 300)
    return rng.choice(SYMS)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    rng = random.Random(7)
    cases = []
    for _ in range(n):
        if rng.random() < 0.5:  # mostly valid: generate from a grammar
            stmt = lambda: rng.choice([
                f"sound {rng.choice(S.SOUNDS)}", f"face {rng.choice(S.FACES)}", f"wait {rng.randint(1, 3000)}",
                "beep", f"vol {rng.randint(0, 100)}", f"show {rng.choice(S.READINGS)}", f"led {rng.choice(S.COLORS)}"])
            body = "; ".join(stmt() for _ in range(rng.randint(1, 4)))
            form = rng.choice([body, f"repeat {rng.randint(1, 20)} {{ {body} }}",
                               f"if {rng.choice(S.READINGS)} {rng.choice(S.OPS)} {rng.randint(-60, 100)} {{ {body} }}"
                               + (f" else {{ {stmt()} }}" if rng.random() < 0.5 else "")])
            cases.append(form)
        else:
            cases.append(" ".join(piece(rng) for _ in range(rng.randint(1, 14))))
    bad = [(c, S.check(c)) for c in cases
           if subprocess.run([str(HOST), "--script", c], capture_output=True, text=True).stdout.strip() != S.check(c)]
    print(f"scripts: python == C on {n - len(bad)} of {n} fuzz cases", bad[:3])
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
