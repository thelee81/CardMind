"""Score the device assistant on fresh questions with random simulated readings.

Runs the PC build of the device code (firmware/host/host_chat; /status sets the readings) and
reports per request type:
  stated   - the reply contains the Device line's key value (first number, or its key word)
  invented - the reply contains a number that is not in the ctx or the question
Plus a few fact questions (card) and "no such sensor" questions.

  python pipeline/eval_device.py data/sd_card/espllm/model.bin[,kb.bin] [more models]
"""
import random
import re
import subprocess
import sys
from dataclasses import asdict

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from lib import devtext as D  # noqa: E402
from lib.common import ROOT, SD_DIR  # noqa: E402

HOST = ROOT / "firmware" / "host" / ("host_chat.exe" if sys.platform == "win32" else "host_chat")
NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")

QUESTIONS = {
    D.BATTERY: ["battery level?", "how much battery do i have left", "check the battery voltage"],
    D.TEMP: ["how warm is the chip right now", "temp?", "is the cpu running hot"],
    D.MEMORY: ["free memory?", "how much heap is left", "ram check"],
    D.SD: ["is an sd card inserted", "how full is the sd card", "storage?"],
    D.MIC: ["is it noisy here", "measure the noise", "mic level?"],
    D.WIFI: ["scan wifi networks", "any wifi around?", "how strong is the wifi signal"],
    D.GROVE: ["scan the grove port", "what i2c devices are connected", "anything on grove?"],
    D.UPTIME: ["uptime?", "how long since boot", "how long have you been running"],
    D.SCREEN: ["current screen brightness?", "how bright is the display"],
    D.VOLUME: ["what's the volume at", "speaker volume?"],
    D.CHIP: ["what chip is inside", "mac address?", "cpu speed?"],
    D.STATUS: ["status report", "give me an overview", "system summary"],
    D.LED_SET: ["set the led to orange", "turn the rgb light blue", "led off please"],
    D.BRIGHT_SET: ["set brightness to 60", "dim the screen a bit", "screen brightness max"],
    D.VOL_SET: ["volume 25", "turn the volume up", "mute"],
    D.BEEP: ["beep", "play a test sound"],
    D.IR_SEND: ["send ir address 7 command 21", "transmit infrared address 0x20 command 0x10", "send an ir code"],
}
CARD_QS = ["what pins does the sd card use", "how do i enter download mode", "what is the ir range",
           "how do i use the grove port", "what pin is the rgb led on", "what display does it have",
           "how big is the battery", "does it support bluetooth"]
MISSING_QS = ["what is the humidity", "does it have an accelerometer", "can you take a photo", "is there gps"]


def key_value(line):
    """What a correct reply must contain."""
    body = line[len("Device: "):]
    for word in ("no SD card", "nothing", "not changed", "not sent", "failed", "no networks", "off"):
        if word in body:
            return word.split()[-1]
    m = re.search(r"set to (\w+)\.", body)
    if m and not m.group(1).isdigit():
        return m.group(1)  # LED colour
    m = re.search(r"address (0x[0-9A-F]+)", body)
    if m:
        return m.group(1)
    nums = NUM.findall(body.replace("ESP32-S3", "").replace("SDA G2, SCL G1", ""))
    return nums[0] if nums else body.split()[0]


def run(arg, items):
    model, _, kb = arg.partition(",")
    lines = []
    for st, q in items:
        kv = " ".join(f"{k}={','.join(map(str, v)) if k == 'grove' else v}" for k, v in asdict(st).items()
                      if k not in ("new_bright", "new_vol", "led", "bright_raised", "beep_hz", "beep_ms"))
        lines += [f"/status {kv}", q, "/new"]
    args = [str(HOST), model] + ([kb] if kb else [str(SD_DIR / "kb.bin")])
    out = subprocess.run(args, input="\n".join(lines + ["/quit"]) + "\n", capture_output=True, text=True,
                         timeout=1800).stdout
    got = re.findall(r"bot> ?(.*?)\n  \[ctx\] (.*?)\n", out)
    assert len(got) == len(items), f"parsed {len(got)} of {len(items)}"
    return got


def main():
    rng = random.Random(11)
    items, kinds = [], []
    for intent, qs in QUESTIONS.items():
        for q in qs:
            for _ in range(3):
                items.append((D.simulate(rng), q))
                kinds.append(intent)
    for q in CARD_QS + MISSING_QS:
        items.append((D.simulate(rng), q))
        kinds.append("card" if q in CARD_QS else "missing")
    for arg in sys.argv[1:] or [str(SD_DIR / "model.bin")]:
        got = run(arg, items)
        per = {}
        examples = []
        for (st, q), kind, (reply, ctx) in zip(items, kinds, got):
            dev = ctx if ctx.startswith("Device:") else None
            if isinstance(kind, int):
                line = re.match(r"Device: .*?\.(?= [A-Z]|$)", ctx or "")
                line = line.group(0) if line else (dev or "")
                key = key_value(line) if line else None
                stated = bool(key) and key.lower() in reply.lower()
                allowed = set(n.lstrip("-") for n in NUM.findall(ctx + " " + q)) | {str(i) for i in range(11)}
                invented = bool(set(n.lstrip("-") for n in NUM.findall(reply)) - allowed)
                p = per.setdefault(D.NAMES[kind], [0, 0, 0])
                p[0] += 1; p[1] += stated; p[2] += invented
                if len(examples) < 12 and rng.random() < 0.15:
                    examples.append((q, line, reply))
            else:
                examples.append((q, (ctx or "-")[:60], reply))
        tot = [sum(v[i] for v in per.values()) for i in range(3)]
        print(f"\n== {arg}\n  device requests: stated {tot[1]}/{tot[0]}, invented a number {tot[2]}/{tot[0]}")
        print("  " + ", ".join(f"{k} {v[1]}/{v[0]}" + (f" ({v[2]} inv)" if v[2] else "") for k, v in per.items()))
        for q, line, reply in examples:
            print(f"    {q!r}\n      [{line[:90]}]\n      -> {reply[:140]}")


if __name__ == "__main__":
    main()
