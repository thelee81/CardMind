"""Score how well a model writes Card scripts.

Fresh requests go through the PC build of the device code (firmware/host/host_chat). For each one:
  script  - the reply is a "Script:" line (over-the-limit requests: no script, or one the interpreter rejects)
  valid   - the script parses (pipeline/lib/scripttext.py, same rules as firmware/src/script.c)
  right   - the canonical script contains every expected piece (e.g. "repeat 5", "led red")

  python pipeline/eval_scripts.py data/sd_card/espllm/model.bin[,kb.bin] [more models]
"""
import re
import subprocess
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from lib import scripttext as SC  # noqa: E402
from lib.common import BOARD, ROOT, SD_DIR  # noqa: E402

HOST = ROOT / "firmware" / "host" / ("host_chat.exe" if sys.platform == "win32" else "host_chat")

# (request, expected pieces of the canonical script; None = no script expected)
CASES = [
    ("blink the led red 5 times", ["repeat 5", "led red", "led off"]),
    ("flash green 3 times", ["repeat 3", "led green"]),
    ("blink the led blue 10 times every half second", ["repeat 10", "led blue", "wait 500"]),
    ("beep 4 times", ["repeat 4", "beep"]),
    ("beep every 5 seconds, 6 times", ["repeat 6", "beep", "wait 5000"]),
    ("beep twice", ["repeat 2", "beep"]),
    ("wait 10 seconds then beep", ["wait 10000", "beep"]),
    ("wait 3 seconds then turn the led purple", ["wait 3000", "led purple"]),
    ("if the battery is below 20 percent beep", ["if battery < 20", "beep"]),
    ("if the chip is over 50 degrees turn the led red else green", ["if temp > 50", "led red", "else", "led green"]),
    ("if it is noisy turn the led red", ["if mic", "led red"]),
    ("if free ram is under 30 kb beep", ["if ram < 30", "beep"]),
    ("show the battery every 10 seconds, 5 times", ["repeat 5", "show battery", "wait 10000"]),
    ("check the noise level every 2 seconds 10 times", ["repeat 10", "show mic", "wait 2000"]),
    ("show the chip temperature 3 times, every 5 seconds", ["repeat 3", "show temp", "wait 5000"]),
    ("send ir address 4 command 8 three times", ["repeat 3", "ir 4 8"]),
    ("send ir address 0x20 command 0x10 twice with a 1 second pause", ["repeat 2", "ir 32 16", "wait 1000"]),
    ("turn the led red then green then blue, 1 second each", ["led red", "led green", "led blue", "wait 1000"]),
    ("police lights 5 times", ["repeat 5", "led red", "led blue"]),
    ("fade the screen from 100 to 20 percent", ["bright 100", "bright 20"]),
    ("set the volume to 20 then beep", ["vol 20", "beep"]),
    ("beep at 1000 hz for half a second", ["beep 1000 500"]),
    ("countdown 5 seconds then flash white", ["wait", "led white"]),
    ("every 10 seconds for a minute, if the room is loud turn the led red, else off",
     ["repeat 6", "if mic", "led red", "led off", "wait 10000"]),
    ("blink yellow 8 times fast", ["repeat 8", "led yellow"]),
    ("beep after 2 minutes", ["wait 60000", "beep"]),
    ("blink the led forever", None),
    ("beep every day at 7 am", None),
    ("blink 500 times", None),
    ("scan wifi every minute", None),
]

# Waveshare ESP32-S3-RLCD-4.2 (CARDMIND_BOARD=rlcd): no LED, backlight or IR; sounds, eyes, room sensor.
RLCD_CASES = [
    ("beep 4 times", ["repeat 4", "beep"]),
    ("beep every 5 seconds, 6 times", ["repeat 6", "beep", "wait 5000"]),
    ("beep twice", ["repeat 2", "beep"]),
    ("wait 10 seconds then beep", ["wait 10000", "beep"]),
    ("play the woof sound 3 times", ["repeat 3", "sound woof"]),
    ("wait 5 seconds then play chime", ["wait 5000", "sound chime"]),
    ("make the eyes happy then sleepy after 10 seconds", ["face happy", "wait 10000", "face sleepy"]),
    ("look angry for 3 seconds then back to normal", ["face angry", "wait 3000", "face normal"]),
    ("if the battery is below 20 percent beep", ["if battery < 20", "beep"]),
    ("if the room is over 28 degrees look sad", ["if room > 28", "face sad"]),
    ("if humidity is above 70 percent play the ufo sound", ["if humid > 70", "sound ufo"]),
    ("if the chip is over 50 degrees beep else play tweet", ["if temp > 50", "beep", "else", "sound tweet"]),
    ("if it is noisy look surprised", ["if mic", "face surprised"]),
    ("if free ram is under 30 kb beep", ["if ram < 30", "beep"]),
    ("show the battery every 10 seconds, 5 times", ["repeat 5", "show battery", "wait 10000"]),
    ("show the room temperature every 30 seconds 4 times", ["repeat 4", "show room", "wait 30000"]),
    ("show the humidity 3 times, every 5 seconds", ["repeat 3", "show humid", "wait 5000"]),
    ("check the noise level every 2 seconds 10 times", ["repeat 10", "show mic", "wait 2000"]),
    ("set the volume to 20 then beep", ["vol 20", "beep"]),
    ("beep at 1000 hz for half a second", ["beep 1000 500"]),
    ("countdown 5 seconds then play honk", ["wait", "sound honk"]),
    ("every 10 seconds for a minute, if the room is loud look angry, else normal",
     ["repeat 6", "if mic", "face angry", "face normal", "wait 10000"]),
    ("beep after 2 minutes", ["wait 60000", "beep"]),
    ("woof forever", None),
    ("beep every day at 7 am", None),
    ("play ribbit 500 times", None),
    ("scan wifi every minute", None),
]
if BOARD == "rlcd":
    CASES = RLCD_CASES


def run(arg):
    model, _, kb = arg.partition(",")
    lines = []
    for q, _ in CASES:
        lines += [q, "/new"]
    args = [str(HOST), model] + ([kb] if kb else [str(SD_DIR / "kb.bin")])
    out = subprocess.run(args, input="\n".join(lines + ["/quit"]) + "\n", capture_output=True, text=True,
                         timeout=1200).stdout
    got = re.findall(r"bot> ?(.*?)\n  \[ctx\]", out)
    assert len(got) == len(CASES), f"parsed {len(got)} of {len(CASES)}"
    return got


def main():
    for arg in sys.argv[1:] or [str(SD_DIR / "model.bin")]:
        got = run(arg)
        n_script = n_valid = n_right = n_limit = n_limit_ok = 0
        rows = []
        for (q, want), reply in zip(CASES, got):
            reply = reply.strip()
            is_script = reply.startswith(SC.PREFIX)
            if want is None:  # over the limit: fine if no script, or the interpreter rejects it
                n_limit += 1
                runs = is_script and SC.parse(reply[len(SC.PREFIX):].strip())[1] is None
                n_limit_ok += not runs
                err = SC.parse(reply[len(SC.PREFIX):].strip())[1] if is_script else None
                rows.append(("BAD" if runs else "ok ", q, reply + (f"  [rejected: {err}]" if err else "")))
                continue
            n_script += is_script
            if not is_script:
                rows.append(("BAD", q, reply))
                continue
            prog, err = SC.parse(reply[len(SC.PREFIX):].strip())
            if err:
                rows.append(("BAD", q, f"{reply}  [{err}]"))
                continue
            n_valid += 1
            text = SC.to_text(prog)
            ok = all(re.search(r"(?<![\w-])" + re.escape(p) + r"(?![\w])", text) for p in want)  # whole numbers
            n_right += ok
            rows.append(("ok " if ok else "BAD", q, text))
        n = len(CASES) - n_limit
        print(f"\n== {arg}\n  script requests: wrote a script {n_script}/{n}, valid {n_valid}/{n}, "
              f"right {n_right}/{n}; over-the-limit not run (no script, or rejected) {n_limit_ok}/{n_limit}")
        for mark, q, r in rows:
            print(f"  {mark} {q!r}\n        {r[:150]}")


if __name__ == "__main__":
    main()
