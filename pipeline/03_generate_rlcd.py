"""Step 3 for the Waveshare ESP32-S3-RLCD-4.2 board: Gemini writes conversations for Card on the RLCD.

Same request kinds and output format as 03_generate_device.py (the Cardputer generator), with the RLCD
readings and actions, the RLCD knowledge cards (lib/rlcd_cards.py) and the script language with sound,
face, room and humid. Run with the board set, so the matcher, cards and data folder are the RLCD ones:

  CARDMIND_BOARD=rlcd python pipeline/03_generate_rlcd.py show            # one prompt of each kind, no API call
  CARDMIND_BOARD=rlcd python pipeline/03_generate_rlcd.py submit          # dry run: request count and cost
  CARDMIND_BOARD=rlcd python pipeline/03_generate_rlcd.py submit --limit 40 --yes   # pilot (needs the user's OK)
  CARDMIND_BOARD=rlcd python pipeline/03_generate_rlcd.py submit --yes    # the full run (needs the user's OK)
  CARDMIND_BOARD=rlcd python pipeline/03_generate_rlcd.py status | collect

Output: data_rlcd/generated/device.jsonl (same rows as the Cardputer step 3; step 4 replays them).
"""
import argparse
import random
import sys
from dataclasses import asdict

from lib import batch
from lib import devtext as D
from lib import scripttext as SC
from lib.common import BOARD, GEN_DIR, cfg, ensure_dirs, write_jsonl
from lib.kbtext import BM25Index
from lib.rlcd_cards import CARDS

if BOARD != "rlcd":
    sys.exit("set CARDMIND_BOARD=rlcd (this generator writes RLCD data into data_rlcd/)")

JOB = "device"
OUT = GEN_DIR / "device.jsonl"
N = 4                      # conversations per request
CARD_REQUESTS_PER_CARD = 6
PERSONA_REQUESTS = 300
SCRIPT_REQUESTS = 250
# requests per reading / action (4 conversations each). New on this board: more; same as the Cardputer:
# fewer (the Cardputer data for them is reused by step 4).
DEV_REQUESTS = {
    D.ROOM: 90, D.CLOCK: 90, D.RADAR: 90, D.PHONE: 80, D.I2C: 90, D.SOUND: 90, D.FACE: 90,
    D.SD: 60, D.MEMORY: 80, D.CHIP: 80, D.STATUS: 90,
    D.BATTERY: 30, D.TEMP: 40, D.MIC: 30, D.WIFI: 30, D.UPTIME: 30, D.VOLUME: 30, D.VOL_SET: 30, D.BEEP: 30,
    D.GROVE: 30, D.SCREEN: 30, D.LED_SET: 30, D.BRIGHT_SET: 30, D.IR_SEND: 30,
}

NAME = cfg.DEVICE_NAME
DESCRIPTION = ("a concise, friendly technical assistant built into a Waveshare ESP32-S3-RLCD-4.2 desk board, for "
               "makers and engineers; it reports the board's live readings, carries out simple actions on the board "
               "and answers questions about the board's hardware from its knowledge cards")
SYSTEM = f"""You write training conversations for {NAME}, {DESCRIPTION}.

The Waveshare ESP32-S3-RLCD-4.2 is a desk board with an ESP32-S3 (16 MB flash, 8 MB PSRAM), a 4.2 inch
black-and-white reflective screen with no backlight, two microphones, a speaker, an SHTC3 room temperature
and humidity sensor, a PCF85063 clock, a TF card slot, an 18650 battery and a 2 x 8 pin header. It has no
RGB LED, no infrared, no Grove port, no keyboard and no voice. Its screen shows animated eyes, a little town
and {NAME}. The user types on a chat web page on a phone or computer; {NAME}'s reply appears on the page
and on the board's screen. When the user asks about a sensor or asks for an action, the firmware does the
measurement or the action itself and shows {NAME} the result as a line starting with "Device:". {NAME}
never measures anything itself.

These conversations train a very small language model, so the style must be simple and consistent.
Rules for {NAME}'s replies:
- 8 to 45 words, never more than 55; one to three short sentences
- plain ASCII only: no emojis, no markdown, no bullet points, no line breaks
- when there is a Device line: start with the result, using the exact numbers, units and names
  from the Device line (for example "The room is 24.6 C with 52% humidity."); then optionally add one
  short, useful interpretation or tip that follows from the Device line or the reference card
- never invent a reading, number, name or result that is not in the Device line, the reference card
  or the user's message; never claim an action happened unless the Device line says so
- if the Device line says the board has no such part, or something failed or is missing, say so
  plainly, and say what to do or what the board can do instead
- chip temperature and room temperature are different readings: name the one the Device line gives
- without a Device line, answer only from the reference card; if the card does not answer the
  question, say you are not sure rather than guess
- never mention the Cardputer, a keyboard, a Grove port, an RGB LED or infrared as parts of this board
- friendly, direct and technical: the user is a maker or engineer; use pin names like G13 when useful
- refer to itself as {NAME} when asked

Rules for the user's messages:
- realistic chat typing: often short or terse ("room temp?", "scan i2c"), sometimes lowercase or with
  a small typo, sometimes a full sentence
- follow the plan for each turn exactly: ask for what the plan says, in your own words
- an action request is phrased as a request or command ("play the woof sound", "look happy", "set the
  volume to 30"), never starting with what, how, is, does or which"""

SCHEMA = {
    "type": "object",
    "properties": {"conversations": {"type": "array", "items": {
        "type": "object",
        "properties": {"turns": {"type": "array", "items": {
            "type": "object",
            "properties": {"user": {"type": "string"}, "assistant": {"type": "string"}},
            "required": ["user", "assistant"], "additionalProperties": False}}},
        "required": ["turns"], "additionalProperties": False}}},
    "required": ["conversations"], "additionalProperties": False,
}

# What the user asks for, per reading: (plan text, words the message must use). The words keep the
# message inside what the matcher (devtext.dev_parse with the RLCD board) understands.
ASK = {
    D.BATTERY: ("asks about the battery (level, voltage or how much is left)", "battery, charge or voltage"),
    D.TEMP: ("asks how hot the chip or processor is (the ESP32-S3's own temperature, not the room)",
             "chip, cpu or processor, together with temperature, temp or hot"),
    D.ROOM: ("asks about the room: temperature, humidity, or how warm or humid it is",
             "room, humidity, humid, temperature, temp, hot, warm or cold"),
    D.CLOCK: ("asks the time, the date or the day", "time, clock, date, day or today"),
    D.RADAR: ("asks whether anyone or anything is moving nearby (the radar)",
              "radar, motion, moving, anyone, someone, people or person"),
    D.PHONE: ("asks whether the phone is connected (Bluetooth, the Chronos app)", "phone, bluetooth, ble or chronos"),
    D.I2C: ("asks for an I2C scan or what devices are on the I2C bus",
            "i2c together with scan, devices, connected or found"),
    D.MEMORY: ("asks about free RAM, PSRAM, memory or flash", "ram, psram, memory, heap or flash"),
    D.SD: ("asks about the TF / SD card (is one inserted, size or space used)", "sd, sd card, tf card or storage"),
    D.MIC: ("asks how loud or noisy it is around the board (the microphone sound level)",
            "noise, noisy, loud, quiet, mic or microphone"),
    D.WIFI: ("asks for a Wi-Fi scan or about nearby networks and signal", "wifi, wi-fi, networks or signal"),
    D.UPTIME: ("asks how long the board has been running since boot", "uptime, running or since boot"),
    D.VOLUME: ("asks what the speaker volume is now", "volume or speaker"),
    D.CHIP: ("asks about the chip: model, revision, CPU speed, MAC address or ESP-IDF version",
             "chip, cpu, mac, esp32 or firmware"),
    D.STATUS: ("asks for an overall status report of the board", "status, summary, overview or everything"),
    D.GROVE: ("asks what is plugged into the Grove port (the board has none)", "grove or port"),
    D.SCREEN: ("asks what the screen brightness is (the reflective screen has no backlight)",
               "brightness, backlight or screen"),
}
CANON = {  # query that finds the reference card for an intent
    D.BATTERY: "battery reading ADC G4 divider percentage", D.TEMP: "internal temperature sensor measures silicon",
    D.ROOM: "SHTC3 temperature humidity sensor 0x70", D.CLOCK: "clock reading local time day date",
    D.RADAR: "radar reading moving targets nearest", D.PHONE: "Bluetooth Chronos app pair RLCD Eyes",
    D.I2C: "I2C scan probes address board chips", D.MEMORY: "free RAM internal heap largest free block PSRAM",
    D.SD: "SD card reading type total size used espllm", D.MIC: "sound level reading dBFS microphones",
    D.WIFI: "Wi-Fi signal strength RSSI dBm channels", D.UPTIME: "clock reading uptime since boot",
    D.VOLUME: "speaker header volume percent", D.CHIP: "revision MAC address eFuse ESP-IDF",
    D.STATUS: "Card reads battery room temperature humidity time radar", D.GROVE: "no Grove port header P1 I2C",
    D.SCREEN: "reflective screen no backlight brightness", D.VOL_SET: "speaker header volume percent mute",
    D.BEEP: "named sounds speaker beep tone", D.SOUND: "named sounds chime woof ribbit",
    D.FACE: "eyes show emotions look happy", D.LED_SET: "two indicator LEDs no RGB LED CHG WRN",
    D.BRIGHT_SET: "reflective screen no backlight brightness", D.IR_SEND: "no RGB LED infrared Grove keyboard",
}
FOLLOW_UPS = [
    "asks whether that is good, normal or a problem",
    "asks a short why or what-does-that-mean question about the previous answer",
    "says thanks or ok",
]
SOUND_WORDS = {"woof": ["bark", "dog"], "ribbit": ["frog", "croak"], "tweet": ["bird", "chirp"], "honk": ["horn"],
               "ring": ["bell"], "ufo": ["alien"], "thunder": ["storm"], "roar": ["lion"]}
FACE_WORDS = {"happy": ["smile"], "sad": ["frown", "cry"], "angry": ["mad"], "surprised": ["shocked"],
              "sleepy": ["tired"], "suspicious": ["wink"], "confused": ["puzzled"], "love": ["heart"]}
PERSONA_THEMES = [
    "greetings and asking who or what the assistant is",
    "asking what the assistant can do or for help with commands",
    "asking for a sensor or part this board does not have (accelerometer or IMU, GPS, light level, camera, "
    "CO2, an RGB LED, infrared, a keyboard, a touchscreen)",
    "asking for something outside the board (weather forecast, news, maths homework, a joke, a recipe)",
    "asking the assistant to do something it cannot do (browse the internet, play music, take a photo, speak "
    "out loud, send a text message, set the screen brightness)",
    "thanks, goodbye, or a compliment",
    "unclear or garbled input (random keys, a single word, a typo-filled message)",
    "the user is frustrated or says the assistant was wrong",
    "safety: the 18650 battery is swollen or hot, the board smells of burning, got wet, or was dropped",
    "asking how the assistant knows the readings, or whether it works offline",
    "a technical question the reference card does not answer (so the reply says it is not sure and suggests "
    "the Waveshare docs or the datasheet)",
    "asking about the eyes, the town screen, the hourly chime or the go-home banner",
]

SYSTEM_SCRIPTS = """
This set is about Card scripts. When the user asks for something repeated, timed, in a sequence or
conditional, Card replies with ONLY one line: "Script: " followed by a script in this language
(statements separated by "; ", blocks in "{ }"):
  sound NAME       NAME: chime woof ribbit tweet honk ring ufo thunder roar notify startup
  face NAME        the eyes' emotion: happy sad angry surprised sleepy suspicious confused love curious,
                   or normal (back to automatic)
  vol N            speaker volume 0 to 100 (percent)
  beep             or beep HZ MS (HZ 100 to 8000, MS 10 to 2000; default 2000 Hz, 200 ms)
  wait MS          1 to 60000 milliseconds (seconds x 1000)
  show READING     prints a reading on the chat page
  repeat N { ... } N from 1 to 100
  if READING OP N { ... } else { ... }    OP: < > <= >= == !=   (else is optional)
READING: room (room temperature, C), humid (room humidity, percent), battery (percent), temp (chip, C),
mic (sound level, dBFS, negative), ram (free KB), uptime (seconds), vol (percent).
This board has no LED, no screen brightness and no infrared, so scripts never use led, bright or ir.
Limits: at most 200 characters, 10 minutes of total waiting, 2000 steps.
Examples:
  bark 3 times -> Script: repeat 3 { sound woof; wait 800 }
  look happy for 10 seconds then go back to normal -> Script: face happy; wait 10000; face normal
  if the room is over 28 degrees look sad, else look happy -> Script: if room > 28 { face sad } else { face happy }
  check the humidity every 10 seconds for a minute -> Script: repeat 6 { show humid; wait 10000 }
Rules for script replies:
- use exactly the numbers, names and counts the user gave; convert seconds to milliseconds
- when the user gives no number, choose a sensible one (between sounds: 600 to 1500 ms; checks: every 5 to 10 s)
- nothing before or after the script line: no explanation, no quotes
- the board runs the script only after the user presses Run on the page, so never claim it already ran
- one wait is at most 60000 ms: write longer waits as repeat N { wait 60000 }
If the request cannot be a script (runs forever, at a clock time, longer than 10 minutes, more than
100 repeats, Wi-Fi or I2C scans, the LED, brightness or infrared, songs or sounds not in the list), Card
answers in one or two plain sentences, says the limit, and offers what it can do instead (no Script line).
Rules for the user's messages: commands, not questions ("bark twice", "can you beep 3 times"); mention how
often or how long when the theme suggests it; vary the wording a lot."""
SCRIPT_THEMES = [
    "playing a named sound a number of times or every few seconds, sometimes with a pause given",
    "showing an emotion for some seconds and then going back to normal, or a sequence of emotions",
    "beeping a number of times or every few seconds, sometimes with a pitch or length",
    "watching a reading every few seconds for a while (room, humid, battery, temp, mic, ram)",
    "a condition on the room temperature or humidity with a sound or a face (too hot, too humid, too cold, too dry), sometimes with else",
    "a repeated check with a condition inside (every few seconds: if noisy look surprised, else normal)",
    "a countdown or a timer (wait some seconds or minutes, then a sound, a beep or a face)",
    "a short sequence mixing actions (sound, face, beep, volume, show a reading)",
    "a condition on the battery or the chip temperature with a sound or a face",
    "a follow-up that changes the previous script: faster, slower, more times, another sound, face or reading",
    "stepping the volume up or down with a beep or a sound at each step",
    "requests that go over the limits or need missing parts (forever, every morning at 7, for an hour, 500 times, blink an LED, dim the screen, send infrared, play a song)",
]


def card_index():
    return BM25Index(CARDS)


def card_for(ix, intent):
    _, pid = ix.search(CANON[intent])
    return CARDS[pid] if pid >= 0 else None


def action_turn(rng, intent):
    """(plan text, a parseable example message) for an action turn; the example fixes the arguments."""
    if intent == D.VOL_SET:
        kind = rng.choice(["num", "num", "up", "down", "mute", "vague"])
        if kind == "num":
            v = rng.randrange(0, 101, rng.choice([5, 10]))
            return f"asks to set the volume to {v} percent", f"set the volume to {v}"
        if kind == "up":
            return "asks to turn the volume up (no number)", "turn the volume up"
        if kind == "down":
            return "asks to turn the volume down (no number)", "turn the volume down"
        if kind == "mute":
            return "asks to mute the speaker", "mute the speaker"
        return "asks to change the volume but gives no amount or direction", "change the volume"
    if intent == D.BEEP:
        return "asks the board to beep or play a test tone", "beep"
    if intent == D.SOUND:
        name = rng.choice(D.SOUNDS)
        word = rng.choice([name, name] + SOUND_WORDS.get(name, []))
        return (f"asks to play the {name} sound (the message must contain the word '{word}')",
                f"play the {word} sound" if word == name else word)
    if intent == D.FACE:
        name = rng.choice(D.FACES)
        if name == "normal":
            return "asks the eyes to go back to normal", "look normal again"
        word = rng.choice([name, name] + FACE_WORDS.get(name, []))
        if name == "love":
            return ("asks the eyes to look in love (the message must contain 'love' or 'heart' and one of: face, "
                    "eyes, look)", rng.choice(["look in love", "make a heart face"]))
        return (f"asks the eyes to look {name} (the message must contain the word '{word}' and one of: face, "
                f"eyes, look, expression, mood)", f"look {word}" if word == name else f"make a {word} face")
    if intent == D.LED_SET:
        c = rng.choice(D.COLORS[1:] + ["off", "on"])
        if c in ("on", "off"):
            return f"asks to turn the RGB LED {c} (the board has none)", f"turn the led {c}"
        return f"asks to set the RGB LED to {c} (the board has none)", f"make the led {c}"
    if intent == D.BRIGHT_SET:
        v = rng.randrange(10, 101, 10)
        return rng.choice([(f"asks to set the screen brightness to {v} percent", f"set the brightness to {v}"),
                           ("asks to dim the screen", "dim the screen"),
                           ("asks to make the screen brighter", "make the screen brighter")])
    if intent == D.IR_SEND:
        a, c = rng.randrange(256), rng.randrange(256)
        return (f"asks to send an infrared code with address {a} and command {c} (the board has no IR)",
                f"send ir address {a} command {c}")
    raise ValueError(intent)


def plan_conversation(rng, intent):
    """A turn plan [(plan text, example or None, intent)] plus the simulated board status."""
    st = D.simulate(rng)
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
            nxt = rng.choice([i for i in ASK if i not in (intent, D.GROVE, D.SCREEN)])
            turns.append((f"then {ASK[nxt][0]}; the message must use one of: {ASK[nxt][1]}", None, nxt))
        else:
            nxt = rng.choice([D.VOL_SET, D.BEEP, D.SOUND, D.SOUND, D.FACE, D.FACE])
            text, example = action_turn(rng, nxt)
            turns.append(("then " + text, example, nxt))
    return st, turns


def render_plan(st0, turns):
    """Text for the writer: each turn's request and the Device line the assistant will see."""
    st = D.DevStatus(**asdict(st0))
    lines = []
    for k, (text, example, intent) in enumerate(turns, 1):
        s = f"  Turn {k}: the user {text}."
        if example:
            s += f' (Example wording: "{example}"; vary it but keep the meaning and numbers.)'
        if intent != D.NONE:
            req = D.dev_parse(example) if example else D.DevReq(intent=intent)
            if example and req.intent != intent:
                raise AssertionError(f"example {example!r} parses as {D.NAMES[req.intent]}, not {D.NAMES[intent]}")
            D.dev_plan(req, st)
            s += f"\n    {NAME} is shown: {D.dev_line(req, st)}"
            D.dev_commit(st)
        else:
            s += f"\n    {NAME} is shown no new Device line."
        lines.append(s)
    return "\n".join(lines)


def params(system, user):
    return batch.make_params(cfg.GENERATOR_MODEL, cfg.GENERATOR_EFFORT, system, user, SCHEMA)


def build_items(rng):
    ix = card_index()
    items = []
    for intent, n_req in DEV_REQUESTS.items():
        card = card_for(ix, intent)
        for r in range(n_req):
            convs, plans = [], []
            for k in range(N):
                st, turns = plan_conversation(rng, intent)
                convs.append(f"Conversation {k + 1}:\n{render_plan(st, turns)}")
                plans.append({"status": asdict(st), "turns": [[t, e, i] for t, e, i in turns]})
            user = (f"Reference card ({NAME} can see this):\n{card}\n\n" if card else "") + \
                f"Write {N} conversations, one per plan below, with exactly the turns listed.\n\n" + "\n\n".join(convs)
            items.append((f"dev-{D.NAMES[intent]}-{r:04d}", params(SYSTEM, user),
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
            items.append((f"card-{i:03d}-{r}", params(SYSTEM, user),
                          {"kind": "card", "card": card, "status": asdict(D.simulate(rng))}))
    intro = [c for c in CARDS if c.startswith(("Card is", "Card commands", "You talk to Card"))]
    missing = [c for c in CARDS if "has no" in c]
    eyes = [c for c in CARDS if "eyes" in c and ("emotion" in c or "chime" in c or "five screens" in c)]
    for i in range(PERSONA_REQUESTS):
        t = i % len(PERSONA_THEMES)
        theme = PERSONA_THEMES[t]
        pool = intro if t in (0, 1, 9) else missing if t in (2, 4) else eyes if t == 11 else [None]
        card = rng.choice(pool)
        user = ((f"Reference card ({NAME} can see this):\n{card}\n\n" if card else "") +
                f"Theme: {theme}.\nWrite {N} conversations of 1 to 3 turns on this theme. There is no "
                f"Device line in these conversations; never state a reading.")
        items.append((f"per-{i:04d}", params(SYSTEM, user),
                      {"kind": "persona", "card": card, "status": asdict(D.simulate(rng))}))
    readings = [r for r in SC.READINGS if r != "bright"]
    for i in range(SCRIPT_REQUESTS):
        theme = SCRIPT_THEMES[i % len(SCRIPT_THEMES)]
        hint = (f"Use different details in each conversation, for example: sounds "
                f"{', '.join(rng.sample(SC.SOUNDS, 3))}; faces {', '.join(rng.sample(SC.FACES[1:], 2))}; counts "
                f"{rng.randint(2, 6)} and {rng.randint(7, 20)}; intervals {rng.choice([0.5, 1, 1.5, 2])} s and "
                f"{rng.choice([3, 5, 10, 15, 30])} s; readings {', '.join(rng.sample(readings, 2))}; thresholds "
                f"room {rng.randint(18, 32)} C, humid {rng.randrange(30, 85, 5)}%; wording style: "
                f"{rng.choice(['terse', 'polite full sentences', 'casual with a typo', 'mixed'])}.")
        user = (f"Theme: {theme}.\n{hint}\nWrite {N} conversations of 1 or 2 turns on this theme. In 2-turn "
                f"conversations the second message changes or extends the first request and Card answers with "
                f"a complete new Script line. There is no Device line in these conversations.")
        items.append((f"scr-{i:04d}", params(SYSTEM + SYSTEM_SCRIPTS, user),
                      {"kind": "script", "card": None, "status": asdict(D.simulate(rng))}))
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["submit", "status", "collect", "show"])
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="pilot: only every k-th request, about this many")
    a = ap.parse_args()
    ensure_dirs()
    if a.cmd in ("submit", "show"):
        items = build_items(random.Random(cfg.SEED + 101))
        if a.cmd == "show":  # print one prompt of each kind, no API call
            for prefix in ("dev-room", "dev-sound", "dev-face", "dev-led_set", "dev-status", "card-", "per-0002", "scr-"):
                cid, p, _ = next((it for it in items if it[0].startswith(prefix)), (None, None, None))
                if cid:
                    print(f"===== {cid}\n{p['messages'][0]['content']}\n")
            kinds = {}
            for cid, _, m in items:
                kinds[m["kind"]] = kinds.get(m["kind"], 0) + 1
            print(f"{len(items)} requests: {kinds}")
            return
        if a.limit:  # spread over all kinds and intents; the full run later skips what is done
            items = items[::max(1, len(items) // a.limit)]
        batch.submit(JOB, items, cfg.GENERATOR_MODEL, N * 300 + 800, a.yes)
    elif a.cmd == "status":
        batch.status(JOB)
    else:
        rows = []
        for r in batch.collect(JOB, a.wait):
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
        write_jsonl(OUT, rows)
        print(f"wrote {len(rows)} conversations -> {OUT}")


if __name__ == "__main__":
    main()
