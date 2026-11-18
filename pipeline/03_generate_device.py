"""Step 3 (device assistant): Gemini writes conversations for "Card", the Cardputer assistant.

Three kinds of request (4 conversations each):
  dev-*   the user asks for a reading or an action. For every conversation this script simulates
          the device (devtext.simulate), plans 1 to 3 turns, and shows the writer the exact
          "Device:" line the assistant will see for each turn.
  card-*  the user asks about the hardware; the reply must come from one knowledge card.
  per-*   identity, help, missing sensors, off-topic, thanks, unclear input.

  python pipeline/03_generate_device.py submit           # dry run: prints the request count and cost
  python pipeline/03_generate_device.py submit --yes     # spends money (needs the user's OK)
  python pipeline/03_generate_device.py submit --limit 40 --yes   # small pilot first
  python pipeline/03_generate_device.py submit --round 2 --yes    # round 2: d1's weak spots -> device_r2.jsonl
  python pipeline/03_generate_device.py submit --round 3 --yes    # round 3: Card scripts -> device_r3.jsonl
  python pipeline/03_generate_device.py submit --round 4 --yes    # round 4: d9's weak scripts -> device_r4.jsonl
  python pipeline/03_generate_device.py status
  python pipeline/03_generate_device.py collect

Output: data/generated/device.jsonl
  {"kind", "card", "status", "plan", "turns": [{"user", "bot"}]}
Step 4 (04_build_device_dataset.py) replays the user messages through the same request matcher,
so the training <ctx> is exactly what the device would show.
"""
import argparse
import random
from dataclasses import asdict

from lib import batch
from lib import devtext as D
from lib import scripttext as SC
from lib.common import GEN_DIR, cfg, ensure_dirs, write_jsonl
from lib.device_cards import CARDS
from lib.kbtext import BM25Index

JOB = "device"
OUT = GEN_DIR / "device.jsonl"
N = 4                       # conversations per request
DEV_REQUESTS_PER_INTENT = 110
CARD_REQUESTS_PER_CARD = 6
PERSONA_REQUESTS = 250

NAME = cfg.DEVICE_NAME
SYSTEM = f"""You write training conversations for {NAME}, {cfg.DEVICE_DESCRIPTION}.

The Cardputer v1.1 is a pocket ESP32-S3 computer with a 240 x 135 screen, a 56-key keyboard, a speaker,
a microphone, an IR emitter, an RGB LED, a microSD slot and a Grove port. The user types on the tiny
keyboard and presses Enter; {NAME}'s reply is shown on screen and may be read aloud by a robot voice.
When the user asks about a sensor or asks for an action, the firmware does the measurement or the
action itself and shows {NAME} the result as a line starting with "Device:". {NAME} never measures
anything itself.

These conversations train a very small language model, so the style must be simple and consistent.
Rules for {NAME}'s replies:
- 8 to 45 words, never more than 55; one to three short sentences
- plain ASCII only: no emojis, no markdown, no bullet points, no line breaks
- when there is a Device line: start with the result, using the exact numbers, units and names
  from the Device line (for example "Battery is at 3.92 V, about 78%."); then optionally add one
  short, useful interpretation or tip that follows from the Device line or the reference card
- never invent a reading, number, name or result that is not in the Device line, the reference card
  or the user's message; never claim an action happened unless the Device line says so
- if the Device line says something failed or was not changed, say so plainly and say what to do
- without a Device line, answer only from the reference card; if the card does not answer the
  question, say you are not sure rather than guess
- friendly, direct and technical: the user is a maker or engineer; use pin names like G44 when useful
- refer to itself as {NAME} when asked

Rules for the user's messages:
- realistic typing on a tiny keyboard: often short or terse ("batt?", "wifi scan"), sometimes
  lowercase or with a small typo, sometimes a full sentence
- follow the plan for each turn exactly: ask for what the plan says, in your own words
- an action request is phrased as a request or command ("turn the led green", "can you set the
  volume to 30", "dim the screen"), never starting with what, how, is, does or which"""

SCHEMA = {
    "type": "object",
    "properties": {
        "conversations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "turns": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"user": {"type": "string"}, "assistant": {"type": "string"}},
                            "required": ["user", "assistant"],
                            "additionalProperties": False,
                        },
                    }
                },
                "required": ["turns"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["conversations"],
    "additionalProperties": False,
}

# What the user asks for, per intent: (plan text, words the message must use). The words keep the
# message inside what the device's request matcher (devtext.dev_parse) understands.
ASK = {
    D.BATTERY: ("asks about the battery (level, voltage or how much is left)", "battery, charge or voltage"),
    D.TEMP: ("asks how hot the chip or the device is", "temperature, temp, hot or warm"),
    D.MEMORY: ("asks about free RAM or memory", "ram, memory, heap or flash"),
    D.SD: ("asks about the SD card (is one inserted, size or space used)", "sd, sd card, micro sd or storage"),
    D.MIC: ("asks how loud or noisy it is around the device (the microphone sound level)",
            "noise, noisy, loud, quiet, mic or microphone"),
    D.WIFI: ("asks for a Wi-Fi scan or about nearby networks and signal", "wifi, wi-fi, networks or signal"),
    D.GROVE: ("asks what is plugged into the Grove port (an I2C scan)", "grove, i2c, port or unit"),
    D.UPTIME: ("asks how long the device has been running since boot", "uptime, running or since boot"),
    D.SCREEN: ("asks what the screen brightness is now", "brightness, screen or display"),
    D.VOLUME: ("asks what the speaker volume is now", "volume or speaker"),
    D.CHIP: ("asks about the chip: model, revision, CPU speed, MAC address or ESP-IDF version",
             "chip, cpu, mac, esp32 or firmware"),
    D.STATUS: ("asks for an overall status report of the device", "status, summary, overview or everything"),
}
CANON = {  # query that finds the reference card for an intent
    D.BATTERY: "battery voltage ADC G10 percentage", D.TEMP: "internal temperature sensor chip",
    D.MEMORY: "free RAM largest free block", D.SD: "SD card reading type total size used",
    D.MIC: "sound level reading dBFS", D.WIFI: "Wi-Fi signal strength RSSI dBm channels",
    D.GROVE: "Grove scan probes I2C address Units", D.UPTIME: "uptime time since boot clock",
    D.SCREEN: "screen brightness backlight G38 PWM", D.VOLUME: "volume levels percentages speaker",
    D.CHIP: "chip revision MAC address ESP-IDF", D.STATUS: "Card reads battery chip temperature RAM",
    D.LED_SET: "RGB LED WS2812 power G38 backlight brightness 100", D.BRIGHT_SET: "screen brightness backlight G38 PWM",
    D.VOL_SET: "volume levels percentages speaker mute", D.BEEP: "speaker NS4168 tone beep",
    D.IR_SEND: "NEC infrared address command 38 kHz",
}
FOLLOW_UPS = [
    "asks whether that is good, normal or a problem",
    "asks a short why or what-does-that-mean question about the previous answer",
    "says thanks or ok",
]
PERSONA_THEMES = [
    "greetings and asking who or what the assistant is",
    "asking what the assistant can do or for help with commands",
    "asking for a sensor the Cardputer v1.1 does not have (humidity, room temperature, accelerometer or IMU, GPS, light level, camera, heart rate)",
    "asking for something outside the device (weather, news, maths homework, a joke, the time of day)",
    "asking the assistant to do something it cannot do (connect to Wi-Fi, browse the internet, play music, take a photo, vibrate)",
    "thanks, goodbye, or a compliment",
    "unclear or garbled input (random keys, a single word, a typo-filled message)",
    "the user is frustrated or says the assistant was wrong",
    "safety: the battery is swollen, the device is very hot, smells of burning, or got wet",
    "asking how the assistant knows the readings, or whether it works offline",
]


def card_index():
    return BM25Index(CARDS)


def card_for(ix, intent):
    _, pid = ix.search(CANON[intent])
    return CARDS[pid] if pid >= 0 else None


def action_turn(rng, intent):
    """(plan text, a parseable example message) for an action turn; the example fixes the arguments."""
    if intent == D.LED_SET:
        c = rng.choice(D.COLORS[1:] + ["off", "on"])
        if c == "on":
            return "asks to turn the RGB LED on (no colour given)", "turn on the led"
        if c == "off":
            return "asks to turn the RGB LED off", "led off"
        return f"asks to set the RGB LED to {c}", f"make the led {c}"
    if intent in (D.BRIGHT_SET, D.VOL_SET):
        noun = "screen brightness" if intent == D.BRIGHT_SET else "volume"
        kind = rng.choice(["num", "num", "up", "down", "max" if intent == D.BRIGHT_SET else "mute", "vague"])
        if kind == "num":
            v = rng.randrange(10 if intent == D.BRIGHT_SET else 0, 101, rng.choice([5, 10]))
            return f"asks to set the {noun} to {v} percent", f"set the {noun} to {v}"
        if kind == "up":
            return f"asks to turn the {noun} up (no number)", f"turn the {noun} up"
        if kind == "down":
            return (f"asks to dim the screen (no number)" if intent == D.BRIGHT_SET
                    else "asks to turn the volume down (no number)"), f"turn the {noun} down"
        if kind == "max":
            return "asks for full screen brightness", "screen brightness max"
        if kind == "mute":
            return "asks to mute the speaker", "mute the speaker"
        return f"asks to change the {noun} but gives no amount or direction", f"change the {noun}"
    if intent == D.BEEP:
        return "asks the device to beep or play a test sound", "beep"
    if intent == D.IR_SEND:
        kind = rng.choice(["ok", "ok", "ok", "missing", "range"])
        if kind == "ok":
            a, c = rng.randrange(256), rng.randrange(256)
            fa = rng.choice(["%d", "0x%02x"])
            fc = rng.choice(["%d", "0x%02x"])
            return (f"asks to send an IR code with address {fa % a} and command {fc % c} "
                    f"(the message must say 'address' and 'command' before the numbers)",
                    f"send ir address {fa % a} command {fc % c}")
        if kind == "missing":
            return "asks to send an infrared code but gives no address or command", "send an ir signal"
        a, c = rng.randint(256, 999), rng.randrange(256)
        return (f"asks to send IR with address {a} and command {c} (the message must say 'address' and 'command')",
                f"send ir address {a} command {c}")
    raise ValueError(intent)


def plan_conversation(rng, intent, ix, tweak=None):
    """A turn plan [(plan text, example or None, intent)] plus the simulated device status."""
    st = D.simulate(rng)
    if tweak:
        tweak(rng, st)
    turns = []
    if intent in D.ACTIONS:
        text, example = action_turn(rng, intent)
        turns.append((text, example, intent))
    else:
        turns.append((f"{ASK[intent][0]}; the message must use one of: {ASK[intent][1]}", None, intent))
    for _ in range(rng.choice([0, 0, 1, 1, 2])):
        r = rng.random()
        if r < 0.4:
            turns.append((rng.choice(FOLLOW_UPS) + "; no new reading", None, D.NONE))
        elif r < 0.7:
            nxt = rng.choice([i for i in ASK if i != intent])
            turns.append((f"then {ASK[nxt][0]}; the message must use one of: {ASK[nxt][1]}", None, nxt))
        else:
            nxt = rng.choice(D.ACTIONS)
            text, example = action_turn(rng, nxt)
            turns.append(("then " + text, example, nxt))
    return st, turns


def render_plan(st0, turns, ix):
    """Text for the writer: each turn's request and the Device line the assistant will see."""
    st = D.DevStatus(**asdict(st0))
    lines = []
    for k, (text, example, intent) in enumerate(turns, 1):
        s = f"  Turn {k}: the user {text}."
        if example:
            s += f' (Example wording: "{example}"; vary it but keep the meaning and numbers.)'
        if intent != D.NONE:
            req = D.dev_parse(example) if example else D.DevReq(intent=intent)
            D.dev_plan(req, st)
            s += f"\n    {NAME} is shown: {D.dev_line(req, st)}"
            D.dev_commit(st)
        else:
            s += f"\n    {NAME} is shown no new Device line."
        lines.append(s)
    return "\n".join(lines)


def build_items(rng):
    ix = card_index()
    items = []
    intents = list(ASK) + D.ACTIONS
    for intent in intents:
        card = card_for(ix, intent)
        for r in range(DEV_REQUESTS_PER_INTENT):
            convs, plans = [], []
            for k in range(N):
                st, turns = plan_conversation(rng, intent, ix)
                convs.append(f"Conversation {k + 1}:\n{render_plan(st, turns, ix)}")
                plans.append({"status": asdict(st), "turns": [[t, e, i] for t, e, i in turns]})
            user = (f"Reference card ({NAME} can see this):\n{card}\n\n" if card else "") + \
                f"Write {N} conversations, one per plan below, with exactly the turns listed.\n\n" + \
                "\n\n".join(convs)
            items.append((f"dev-{D.NAMES[intent]}-{r:04d}", batch.make_params(
                cfg.GENERATOR_MODEL, cfg.GENERATOR_EFFORT, SYSTEM, user, SCHEMA),
                {"kind": "device", "intent": intent, "card": card, "plans": plans}))
    angles = [
        "Ask direct questions about this card's facts.",
        "Ask how to use this in an Arduino or PlatformIO sketch.",
        "Describe a problem and ask for help fixing it, using this card.",
        "Ask short, terse questions (two to five words).",
        "Ask about pins, numbers or limits from this card, then a follow-up question.",
        "Ask something partly outside this card in one conversation, so the reply says it is not sure about that part.",
    ]
    for i, card in enumerate(CARDS):
        for r in range(CARD_REQUESTS_PER_CARD):
            user = (f"Reference card ({NAME} can see this):\n{card}\n\n"
                    f"Write {N} conversations of 1 to 3 turns where a maker asks about this card's subject. "
                    f"There is no Device line in these conversations: questions only, no action requests. "
                    f"{angles[r % len(angles)]}")
            items.append((f"card-{i:03d}-{r}", batch.make_params(
                cfg.GENERATOR_MODEL, cfg.GENERATOR_EFFORT, SYSTEM, user, SCHEMA),
                {"kind": "card", "card": card, "status": asdict(D.simulate(rng))}))
    for i in range(PERSONA_REQUESTS):
        theme = PERSONA_THEMES[i % len(PERSONA_THEMES)]
        card = rng.choice([CARDS[3], CARDS[4], CARDS[5]] if i % len(PERSONA_THEMES) in (0, 1, 9)
                          else [c for c in CARDS if "has no" in c] or [None])
        user = ((f"Reference card ({NAME} can see this):\n{card}\n\n" if card else "") +
                f"Theme: {theme}.\nWrite {N} conversations of 1 to 3 turns on this theme. There is no "
                f"Device line in these conversations; never state a reading.")
        items.append((f"per-{i:04d}", batch.make_params(
            cfg.GENERATOR_MODEL, cfg.GENERATOR_EFFORT, SYSTEM, user, SCHEMA),
            {"kind": "persona", "card": card, "status": asdict(D.simulate(rng))}))
    return items


# Round 2 (--round 2): more data where d1 was weak (eval_device.py): the long status line, SD sizes,
# Grove scans that find nothing, chip info, plus memory / Wi-Fi / volume / battery and missing sensors.
SYSTEM_R2_EXTRA = """
Extra rules for this set:
- copy every number, unit and name from the Device line exactly, in the same order; for a long
  Device line (status, memory, SD card) repeat all of its values, do not round or drop any
- when a scan found nothing, or there is no SD card, say that first, then give one tip
- the user's follow-up questions are about the values just reported; answer from those values"""
R2_INTENTS = {D.STATUS: 120, D.SD: 90, D.GROVE: 90, D.CHIP: 60, D.MEMORY: 60, D.WIFI: 60, D.VOLUME: 40,
              D.BATTERY: 40}
R2_PERSONA = 60
R2_PERSONA_THEMES = [
    "asking for a sensor the Cardputer v1.1 does not have: GPS, humidity, light level, camera, accelerometer, compass, heart rate",
    "asking it to do something it cannot do: take a photo, connect to the internet, play music, set an alarm, vibrate",
]


def _tweak_r2(intent):
    def tweak(rng, st):
        if intent == D.SD and rng.random() < 0.5:
            st.sd_type, st.sd_total_mb, st.sd_used_mb = 0, 0, 0
        if intent == D.GROVE and rng.random() < 0.5:
            st.grove = []
    return tweak


def build_items_r2(rng):
    ix = card_index()
    system = SYSTEM + SYSTEM_R2_EXTRA
    items = []
    for intent, n_req in R2_INTENTS.items():
        card = card_for(ix, intent)
        for r in range(n_req):
            convs, plans = [], []
            for k in range(N):
                st, turns = plan_conversation(rng, intent, ix, _tweak_r2(intent))
                convs.append(f"Conversation {k + 1}:\n{render_plan(st, turns, ix)}")
                plans.append({"status": asdict(st), "turns": [[t, e, i] for t, e, i in turns]})
            user = (f"Reference card ({NAME} can see this):\n{card}\n\n" if card else "") + \
                f"Write {N} conversations, one per plan below, with exactly the turns listed.\n\n" + \
                "\n\n".join(convs)
            items.append((f"r2dev-{D.NAMES[intent]}-{r:04d}", batch.make_params(
                cfg.GENERATOR_MODEL, cfg.GENERATOR_EFFORT, system, user, SCHEMA),
                {"kind": "device", "intent": intent, "card": card, "plans": plans}))
    missing = [c for c in CARDS if "has no" in c]
    for i in range(R2_PERSONA):
        theme = R2_PERSONA_THEMES[i % len(R2_PERSONA_THEMES)]
        card = rng.choice(missing)
        user = (f"Reference card ({NAME} can see this):\n{card}\n\nTheme: {theme}.\nWrite {N} conversations of "
                f"1 to 3 turns on this theme. There is no Device line in these conversations; never state a "
                f"reading. Say plainly what the Cardputer cannot do, and suggest a Grove Unit when one fits.")
        items.append((f"r2per-{i:04d}", batch.make_params(
            cfg.GENERATOR_MODEL, cfg.GENERATOR_EFFORT, system, user, SCHEMA),
            {"kind": "persona", "card": card, "status": asdict(D.simulate(rng))}))
    return items


# Round 3 (--round 3): Card scripts (pipeline/lib/scripttext.py, firmware/src/script.c).
SYSTEM_R3_EXTRA = """
This set is about Card scripts. When the user asks for something repeated, timed, in a sequence or
conditional, Card replies with ONLY one line: "Script: " followed by a script in this language
(statements separated by "; ", blocks in "{ }"):
  led COLOR        COLOR: off red green blue white yellow orange purple pink cyan magenta
  bright N         screen brightness 10 to 100 (percent)
  vol N            speaker volume 0 to 100 (percent)
  beep             or beep HZ MS (HZ 100 to 8000, MS 10 to 2000; default 2000 Hz, 200 ms)
  ir ADDR CMD      NEC infrared, address and command 0 to 255
  wait MS          1 to 60000 milliseconds (seconds x 1000)
  show READING     prints a reading on screen
  repeat N { ... } N from 1 to 100
  if READING OP N { ... } else { ... }    OP: < > <= >= == !=   (else is optional)
READING: battery (percent), temp (chip, C), mic (sound level, dBFS, negative), ram (free KB),
uptime (seconds), bright (percent), vol (percent).
Limits: at most 200 characters, 10 minutes of total waiting, 2000 steps.
Examples:
  blink the led red 5 times -> Script: repeat 5 { led red; wait 300; led off; wait 300 }
  beep every 10 seconds, 6 times -> Script: repeat 6 { beep; wait 10000 }
  if the battery is under 20 percent beep, else show it -> Script: if battery < 20 { beep } else { show battery }
Rules for script replies:
- use exactly the numbers, colours and counts the user gave; convert seconds to milliseconds
- when the user gives no number, choose a sensible one (blink: 300 to 500 ms; checks: every 5 to 10 s)
- nothing before or after the script line: no explanation, no quotes
- the device runs the script only after the user presses Enter, so never claim it already ran
- one wait is at most 60000 ms: write longer waits as several, e.g. 2 minutes = wait 60000; wait 60000
If the request cannot be a script (runs forever, at a clock time, longer than 10 minutes, more than
100 repeats, Wi-Fi or Grove scans, sounds or tunes it cannot make), Card answers in one or two plain
sentences, says the limit, and offers what it can do instead (no Script line).
Rules for the user's messages: commands, not questions ("blink the led 3 times", "can you beep twice");
mention how often or how long when the theme suggests it; vary the wording a lot."""
R3_THEMES = [
    "blinking the LED in one colour a number of times, sometimes with a given speed",
    "alternating or cycling LED colours (police lights, traffic light, rainbow, red then green then blue)",
    "beeping a number of times or every few seconds, sometimes with a pitch or length",
    "watching a reading every few seconds for a while (battery, temp, mic, ram)",
    "a condition on a reading with an action (battery low, chip hot, room noisy, low RAM), sometimes with else",
    "a repeated check with a condition inside (every few seconds: if noisy turn the led red, else off)",
    "sending an infrared code several times with a pause, or two different codes in a row",
    "fading or stepping the screen brightness or the volume up or down",
    "a countdown or a timer (wait some seconds or minutes, then beep or flash)",
    "a short sequence mixing actions (led, beep, brightness, volume, show a reading)",
    "a follow-up that changes the previous script: faster, slower, more times, another colour or reading",
    "requests that go over the limits (forever, every day at 7, for an hour, 500 times, play a song, scan wifi every minute)",
]
R3_REQUESTS = 450


def build_items_r3(rng):
    system = SYSTEM + SYSTEM_R3_EXTRA
    items = []
    for i in range(R3_REQUESTS):
        theme = R3_THEMES[i % len(R3_THEMES)]
        hint = (f"Use different details in each conversation, for example: colours "
                f"{', '.join(rng.sample(D.COLORS[1:], 3))}; counts {rng.randint(2, 6)} and {rng.randint(7, 20)}; "
                f"intervals {rng.choice([0.2, 0.25, 0.5, 1, 2])} s and {rng.choice([3, 5, 10, 15, 30])} s; "
                f"readings {', '.join(rng.sample(SC.READINGS, 2))}; wording style: "
                f"{rng.choice(['terse', 'polite full sentences', 'casual with a typo', 'mixed'])}.")
        user = (f"Theme: {theme}.\n{hint}\nWrite {N} conversations of 1 or 2 turns on this theme. In 2-turn "
                f"conversations the second message changes or extends the first request and Card answers with "
                f"a complete new Script line. There is no Device line in these conversations.")
        items.append((f"r3scr-{i:04d}", batch.make_params(
            cfg.GENERATOR_MODEL, cfg.GENERATOR_EFFORT, system, user, SCHEMA),
            {"kind": "script", "card": None, "status": asdict(D.simulate(rng))}))
    return items


# Round 4 (--round 4): d9's weak scripts (eval_scripts.py): hex IR codes, waits over a minute,
# colour sequences, fades / steps, fractions of a second.
R4_THEMES = [
    ("sending an infrared code given in hex (0x..), several times or with a pause; the script uses the "
     "decimal values (0x20 = 32, 0x10 = 16, 0xFF = 255)"),
    ("a timer of 2 to 10 minutes, then beep or flash; one wait is at most 60000 ms, so write "
     "repeat N { wait 60000 } or several wait 60000"),
    ("checking a reading every minute or every 30 s for a few minutes (at most 10 minutes in total)"),
    ("a sequence of three or four LED colours, each shown for a given time, sometimes repeated; "
     "every colour named in the request appears in the script in that order"),
    ("fading or stepping the screen brightness from one level to another (each step a bright N with a wait); "
     "the start and end levels the user gives both appear"),
    ("stepping the volume up or down between two levels with a beep at each step"),
    ("timings in fractions of a second (half a second, 0.2 s, a quarter second, 1.5 s) for blinks and beeps"),
    ("a beep with a pitch and length (at 1000 hz for half a second, a low 300 hz beep for 1 s)"),
]
R4_REQUESTS = 240


def build_items_r4(rng):
    system = SYSTEM + SYSTEM_R3_EXTRA
    items = []
    for i in range(R4_REQUESTS):
        theme = R4_THEMES[i % len(R4_THEMES)]
        hx = rng.sample(range(256), 2)
        hint = (f"Use different details in each conversation, for example: colours "
                f"{', '.join(rng.sample(D.COLORS[1:], 4))}; counts {rng.randint(2, 6)} and {rng.randint(7, 12)}; "
                f"minutes {rng.randint(2, 10)}; hex codes 0x{hx[0]:02X} and 0x{hx[1]:02x}; "
                f"brightness {rng.choice([100, 90, 80])} to {rng.choice([10, 20, 30, 40])}; wording style: "
                f"{rng.choice(['terse', 'polite full sentences', 'casual with a typo', 'mixed'])}.")
        user = (f"Theme: {theme}.\n{hint}\nWrite {N} conversations of 1 turn on this theme. Every script must "
                f"stay within the limits; double-check that each number the user gave is in the script "
                f"(seconds and minutes as milliseconds). There is no Device line in these conversations.")
        items.append((f"r4scr-{i:04d}", batch.make_params(
            cfg.GENERATOR_MODEL, cfg.GENERATOR_EFFORT, system, user, SCHEMA),
            {"kind": "script", "card": None, "status": asdict(D.simulate(rng))}))
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["submit", "status", "collect", "show"])
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="pilot: only every k-th request, about this many")
    ap.add_argument("--round", type=int, default=1, help="2 = more data for d1's weak spots")
    a = ap.parse_args()
    ensure_dirs()
    job = JOB if a.round == 1 else f"{JOB}_r{a.round}"
    out = OUT if a.round == 1 else GEN_DIR / f"device_r{a.round}.jsonl"
    if a.cmd in ("submit", "show"):
        items = (build_items(random.Random(cfg.SEED + 77)) if a.round == 1
                 else build_items_r2(random.Random(cfg.SEED + 78)) if a.round == 2
                 else build_items_r3(random.Random(cfg.SEED + 79)) if a.round == 3
                 else build_items_r4(random.Random(cfg.SEED + 80)))
        if a.cmd == "show":  # print one prompt of each kind, no API call
            for prefix in ("dev-led_set", "dev-battery", "card-", "per-", "r2dev-status", "r2dev-grove", "r2per-", "r3scr-", "r4scr-"):
                cid, p, _ = next((it for it in items if it[0].startswith(prefix)), (None, None, None))
                if cid is None:
                    continue
                print(f"===== {cid}\n{p['messages'][0]['content']}\n")
            print(f"{len(items)} requests")
            return
        if a.limit:  # spread over all kinds and intents; the full run later skips what is done
            items = items[::max(1, len(items) // a.limit)]
        batch.submit(job, items, cfg.GENERATOR_MODEL, N * 300 + 800, a.yes)
    elif a.cmd == "status":
        batch.status(job)
    else:
        rows = []
        for r in batch.collect(job, a.wait):
            m = r["meta"]
            for k, conv in enumerate(r["data"].get("conversations", [])):
                turns = [{"user": t["user"], "bot": t["assistant"]} for t in conv.get("turns", [])]
                if not turns:
                    continue
                if m["kind"] == "device":
                    if k >= len(m["plans"]):
                        continue
                    pl = m["plans"][k]
                    rows.append({"kind": "device", "card": m["card"], "status": pl["status"],
                                 "plan": pl["turns"], "turns": turns})
                else:
                    rows.append({"kind": m["kind"], "card": m["card"], "status": m["status"], "plan": None,
                                 "turns": turns})
        write_jsonl(out, rows)
        print(f"wrote {len(rows)} conversations -> {out}")


if __name__ == "__main__":
    main()
