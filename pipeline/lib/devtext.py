"""Device requests: which sensor to read or action to take, and the "Device:" line the model sees.

Python twin of firmware/src/device.c (keep the two identical, then run pipeline/verify.py).

  dev_parse(text)        -> DevReq   (what the user asked for; pure text rules)
  dev_plan(req, st)      -> fills the action targets in st (new brightness, LED colour, ...)
  dev_line(req, st)      -> "Device: battery 3.92 V, about 78%."  or None
  simulate(rng, req)     -> a realistic DevStatus, for training data (Python only)

On the Cardputer, firmware/src/hw.cpp reads the real sensors into a DevStatus, calls
dev_plan, carries out the action, then dev_line. All numbers are integers so C and Python
format them identically.
"""
import random
from dataclasses import dataclass, field
from typing import List

# Intent ids: same order as enum DevIntent in device.h
(NONE, BATTERY, TEMP, MEMORY, SD, MIC, WIFI, GROVE, UPTIME, SCREEN, VOLUME, CHIP, STATUS,
 LED_SET, BRIGHT_SET, VOL_SET, BEEP, IR_SEND) = range(18)
NAMES = ["none", "battery", "temp", "memory", "sd", "mic", "wifi", "grove", "uptime", "screen", "volume",
         "chip", "status", "led_set", "bright_set", "vol_set", "beep", "ir_send"]
READS = list(range(BATTERY, STATUS + 1))
ACTIONS = list(range(LED_SET, IR_SEND + 1))

# arg codes for brightness / volume
ARG_NONE, ARG_UP, ARG_DOWN = -1, -2, -3
COLORS = ["off", "red", "green", "blue", "white", "yellow", "orange", "purple", "pink", "cyan", "magenta"]
COLOR_RGB = [0x000000, 0xFF0000, 0x00FF00, 0x0000FF, 0xFFFFFF, 0xFFFF00, 0xFF8000, 0x8000FF, 0xFF60A0,
             0x00FFFF, 0xFF00FF]
SD_TYPES = ["none", "MMC", "SDSC", "SDHC"]
MAX_WORDS = 48
WORD_LEN = 15
MAX_ADDRS = 8

# Grove I2C addresses of common M5Stack Units (shown as "probably ...")
I2C_NAMES = {
    0x23: "BH1750 light", 0x29: "VL53L0X distance", 0x38: "AHT20 temperature and humidity",
    0x3C: "SSD1306 OLED", 0x44: "SHT30 or SHT40 temperature and humidity", 0x48: "ADS1115 ADC",
    0x5A: "MLX90614 infrared thermometer", 0x62: "SCD40 CO2", 0x68: "MPU6886 IMU",
    0x70: "QMP6988 pressure", 0x76: "BMP280 pressure", 0x77: "BMP280 pressure",
}


@dataclass
class DevReq:
    intent: int = NONE
    arg: int = ARG_NONE      # brightness/volume percent, ARG_UP, ARG_DOWN; LED colour index
    ir_addr: int = -1
    ir_cmd: int = -1
    script: int = 0          # 1 = a Card script request (repeat / timing / condition words)


@dataclass
class DevStatus:
    bat_mv: int = 0
    bat_pct: int = 0
    temp_c10: int = 0          # chip temperature in tenths of a degree C
    heap_kb: int = 0
    block_kb: int = 0
    flash_mb: int = 8
    model_kb: int = 0
    ctx_len: int = 0
    sd_type: int = 0           # index into SD_TYPES; 0 = no card
    sd_total_mb: int = 0
    sd_used_mb: int = 0
    mic_dbfs: int = 0
    wifi_ok: int = 1           # 0 = scan failed (not enough RAM)
    wifi_n: int = 0
    wifi_ssid: str = ""
    wifi_rssi: int = 0
    wifi_ch: int = 0
    grove: List[int] = field(default_factory=list)
    uptime_s: int = 0
    bright: int = 100          # screen brightness percent
    vol: int = 50              # speaker volume percent
    voice_on: int = 1
    chip_rev: int = 2          # major * 100 + minor
    cpu_mhz: int = 240
    mac: str = "34:85:18:00:00:00"
    idf: str = "v4.4.7"
    # filled by dev_plan
    new_bright: int = -1
    new_vol: int = -1
    led: int = -1
    bright_raised: int = 0
    beep_hz: int = 2000
    beep_ms: int = 200


# ------------------------------------------------------------------ parsing
def _words(text):
    out, cur = [], []
    for ch in text.lower() + " ":
        if "a" <= ch <= "z" or "0" <= ch <= "9":
            cur.append(ch)
        elif cur:
            out.append("".join(cur)[:WORD_LEN])
            cur = []
            if len(out) >= MAX_WORDS:
                break
    # join "wi fi" -> "wifi", "micro sd" -> "microsd"
    joined, i = [], 0
    while i < len(out):
        if i + 1 < len(out) and (out[i], out[i + 1]) in (("wi", "fi"), ("micro", "sd")):
            joined.append(out[i] + out[i + 1]); i += 2
        else:
            joined.append(out[i]); i += 1
    return joined


def _num(w):
    """Decimal or 0x hex number word -> int, else None."""
    if w.startswith("0x") and len(w) > 2 and all(c in "0123456789abcdef" for c in w[2:]) and len(w) <= 10:
        return int(w[2:], 16)
    if w.isdigit() and len(w) <= 9:
        return int(w)
    return None


QUESTION_START = {"is", "are", "does", "do", "what", "whats", "which", "why", "when", "where", "who", "how",
                  "did", "was", "were", "has", "have", "should", "will"}
HOWTO = {"code", "arduino", "sketch", "library", "function", "api", "example", "program", "programming",
         "uiflow", "uiflow2", "platformio", "micropython", "script", "wiring", "gpio", "pinout", "pin", "pins",
         "datasheet", "schematic"}
LED_NOUN = {"led", "rgb", "light", "lights", "lamp", "neopixel", "ws2812"}
LED_ON = {"on", "enable", "illuminate", "up"}
LED_OFF = {"kill", "disable", "dark"}
BRIGHT_NOUN = {"brightness", "backlight", "screen", "display", "lcd"}
VOL_NOUN = {"volume", "vol", "speaker", "voice", "sound", "audio"}
UP = {"up", "increase", "raise", "brighter", "brighten", "louder", "higher", "more"}
DOWN = {"down", "decrease", "lower", "reduce", "dim", "dimmer", "darker", "quieter", "softer", "less"}
SET_VERB = {"set", "turn", "make", "change", "put", "switch", "adjust", "go"}
BEEP_WORD = {"beep", "buzz", "buzzer", "chime", "ding", "tone"}
BEEP_NOUN = {"sound", "audio", "noise"}
BEEP_VERB = {"play", "make", "test", "emit"}
IR_NOUN = {"ir", "infrared", "remote"}
IR_VERB = {"send", "transmit", "fire", "emit", "blast", "press"}

READ_WORDS = [  # (intent, words) in priority order
    (STATUS, {"status", "overview", "summary", "everything", "diagnostic", "diagnostics", "health", "readings"}),
    (BATTERY, {"battery", "batt", "charge", "charging", "charged", "voltage", "volt", "volts"}),
    (TEMP, {"temperature", "temp", "hot", "warm", "heat", "overheating", "overheat", "celsius", "degrees"}),
    (SD, {"sd", "microsd", "card", "storage"}),
    (MIC, {"mic", "microphone", "noise", "noisy", "loud", "loudness", "decibel", "decibels", "db", "dbfs",
           "quiet", "hear", "listen"}),
    (WIFI, {"wifi", "wlan", "network", "networks", "ssid", "router", "hotspot", "rssi", "internet", "signal",
            "signals"}),
    (GROVE, {"grove", "i2c", "port", "unit", "units", "hy2"}),
    (UPTIME, {"uptime", "boot", "booted", "running"}),
    (MEMORY, {"ram", "mem", "memory", "heap", "psram", "flash"}),
    (SCREEN, {"brightness", "backlight", "screen", "display", "lcd"}),
    (VOLUME, {"volume", "vol", "speaker"}),
    (CHIP, {"chip", "cpu", "processor", "mcu", "esp32", "esp32s3", "mac", "firmware", "idf", "mhz", "cores"}),
]
GROVE_WEAK = {"plugged", "attached", "connected"}
# Repetition / timing / conditions: the model writes a Card script instead of one instant action.
SCRIPT_CUES = {"times", "twice", "thrice", "every", "repeat", "repeatedly", "loop", "blink", "blinking", "flashing",
               "strobe", "wait", "then", "after", "seconds", "second", "secs", "sec", "ms", "milliseconds", "minute",
               "minutes", "if", "when", "until", "while", "script", "instead", "cycle", "alternate", "sequence",
               "countdown", "forever", "fade", "fading", "ramp", "pulse", "pulsing", "police", "rainbow", "hz"}  # count for Grove only when nothing else matched


def dev_parse(text: str) -> DevReq:
    w = _words(text)
    s = set(w)
    r = DevReq()
    if not w:
        return r
    question = w[0] in QUESTION_START
    howto = bool((s - {"code"} if s & IR_NOUN else s) & HOWTO) or any(w[i] == "how" and w[i + 1] in ("to", "do", "can", "would", "should")
                                   for i in range(len(w) - 1))
    nums = [n for n in (_num(x) for x in w) if n is not None]
    if not question and s & SCRIPT_CUES:
        r.script = 1  # a script request: no instant action or reading; the ctx says "Mode: script."
        return r

    if not question and not howto:
        # IR: "send ir address 4 command 8"
        if s & IR_NOUN and s & IR_VERB:
            r.intent = IR_SEND
            for i in range(len(w) - 1):
                n = _num(w[i + 1])
                if n is None:
                    continue
                if w[i] in ("address", "addr") and r.ir_addr < 0:
                    r.ir_addr = n
                elif w[i] in ("command", "cmd", "code") and r.ir_cmd < 0:
                    r.ir_cmd = n
            return r
        # LED: "turn the led red", "led off"
        if s & LED_NOUN:
            for i, c in enumerate(COLORS):
                if c in s:
                    r.intent, r.arg = LED_SET, i
                    return r
            if s & LED_OFF:
                r.intent, r.arg = LED_SET, 0
                return r
            if s & LED_ON:
                r.intent, r.arg = LED_SET, COLORS.index("white")
                return r
        # beep
        if s & BEEP_WORD or (s & BEEP_VERB and s & BEEP_NOUN) or ("test" in s and "speaker" in s) or w[0] == "sound":
            r.intent = BEEP
            return r
        # brightness / volume
        for noun, intent in ((BRIGHT_NOUN, BRIGHT_SET), (VOL_NOUN, VOL_SET)):
            if not s & noun:
                continue
            if nums:
                r.intent, r.arg = intent, min(nums[0], 100)
            elif intent == BRIGHT_SET and s & {"max", "maximum", "full", "brightest"}:
                r.intent, r.arg = intent, 100
            elif intent == VOL_SET and s & {"mute", "silent", "silence", "off", "zero"}:
                r.intent, r.arg = intent, 0
            elif s & UP:
                r.intent, r.arg = intent, ARG_UP
            elif s & DOWN:
                r.intent, r.arg = intent, ARG_DOWN
            elif s & SET_VERB:
                r.intent, r.arg = intent, ARG_NONE
            if r.intent:
                return r
        if "mute" in s:
            r.intent, r.arg = VOL_SET, 0
            return r
        if s & {"louder", "quieter", "softer"} and not s & {"room", "here", "noise"}:
            r.intent, r.arg = VOL_SET, ARG_UP if "louder" in s else ARG_DOWN
            return r

    if howto:
        return r  # pins, code, "how do I": a facts question, answered from the knowledge card
    found = []
    for intent, words in READ_WORDS:
        if s & words:
            if intent == MIC and s & {"speaker", "volume"}:
                continue  # "how loud is the speaker" is the volume
            found.append(intent)
    if not found and s & GROVE_WEAK:
        found.append(GROVE)
    if "how" in s and "long" in s and ("on" in s or "been" in s) and UPTIME not in found:
        found.append(UPTIME)
    if TEMP in found and CHIP in found:
        found.remove(CHIP)  # "chip temperature"
    specific = [f for f in found if f != STATUS]
    if not found:
        return r
    # "battery status" is the battery; "status" alone or 3+ topics is the status report
    r.intent = STATUS if (not specific or len(specific) >= 3) else specific[0]
    return r


# ------------------------------------------------------------------ planning (targets of actions)
def dev_plan(r: DevReq, st: DevStatus):
    st.new_bright, st.new_vol, st.led, st.bright_raised = -1, -1, -1, 0
    if r.intent == LED_SET:
        st.led = r.arg
        if r.arg != 0 and st.bright < 100:
            st.new_bright, st.bright_raised = 100, 1
    elif r.intent == BRIGHT_SET and r.arg != ARG_NONE:
        t = st.bright + 20 if r.arg == ARG_UP else st.bright - 20 if r.arg == ARG_DOWN else r.arg
        st.new_bright = max(10, min(100, t))
    elif r.intent == VOL_SET and r.arg != ARG_NONE:
        t = st.vol + 20 if r.arg == ARG_UP else st.vol - 20 if r.arg == ARG_DOWN else r.arg
        st.new_vol = max(0, min(100, t))


def dev_commit(st: DevStatus):
    """After an action: the new values become current (the hardware does this by itself)."""
    if st.new_bright >= 0:
        st.bright = st.new_bright
    if st.new_vol >= 0:
        st.vol = st.new_vol


# ------------------------------------------------------------------ formatting
def _volts(mv):
    return "%d.%02d V" % (mv // 1000, (mv % 1000) // 10)


def _tenths(v):
    sign = "-" if v < 0 else ""
    v = abs(v)
    return "%s%d.%d" % (sign, v // 10, v % 10)


def _size(mb):
    t = (mb * 10 + 512) // 1024  # tenths of a GB, rounded
    return "%d.%d GB" % (t // 10, t % 10) if mb >= 1024 else "%d MB" % mb


def _uptime(s):
    d, h, m = s // 86400, s // 3600 % 24, s // 60 % 60
    if d:
        return "%d d %d h" % (d, h)
    if h:
        return "%d h %d min" % (h, m)
    if m:
        return "%d min %d s" % (m, s % 60)
    return "%d s" % s


def _mic_label(db):
    return "very quiet" if db <= -55 else "quiet" if db <= -40 else "moderate" if db <= -25 else "loud"


def _sd_short(st):
    if not st.sd_type:
        return "no SD card"
    return "SD card %s (%s used)" % (_size(st.sd_total_mb), _size(st.sd_used_mb))


def dev_line(r: DevReq, st: DevStatus):
    i = r.intent
    if i == NONE:
        return None
    if i == BATTERY:
        body = "battery %s, about %d%%." % (_volts(st.bat_mv), st.bat_pct)
    elif i == TEMP:
        body = "chip temperature %s C." % _tenths(st.temp_c10)
    elif i == MEMORY:
        body = ("free RAM %d KB, largest free block %d KB, no PSRAM, flash %d MB, model %s, context %d tokens."
                % (st.heap_kb, st.block_kb, st.flash_mb, _size_kb(st.model_kb), st.ctx_len))
    elif i == SD:
        body = ("SD card %s, %s, %s used." % (SD_TYPES[st.sd_type], _size(st.sd_total_mb), _size(st.sd_used_mb))
                if st.sd_type else "no SD card found.")
    elif i == MIC:
        body = "sound level %d dBFS (%s)." % (st.mic_dbfs, _mic_label(st.mic_dbfs))
    elif i == WIFI:
        if not st.wifi_ok:
            body = "Wi-Fi scan failed, not enough free RAM."
        elif not st.wifi_n:
            body = "Wi-Fi scan found no networks."
        else:
            body = "Wi-Fi scan found %d network%s, strongest %s at %d dBm on channel %d." % (
                st.wifi_n, "" if st.wifi_n == 1 else "s", st.wifi_ssid, st.wifi_rssi, st.wifi_ch)
    elif i == GROVE:
        if not st.grove:
            body = "Grove I2C scan (SDA G2, SCL G1) found nothing."
        else:
            parts = ["0x%02X (%s)" % (a, "probably " + I2C_NAMES[a] if a in I2C_NAMES else "unknown")
                     for a in st.grove[:MAX_ADDRS]]
            body = "Grove I2C scan (SDA G2, SCL G1) found %s." % ", ".join(parts)
    elif i == UPTIME:
        body = "up %s since boot." % _uptime(st.uptime_s)
    elif i == SCREEN:
        body = "screen brightness %d%%." % st.bright
    elif i == VOLUME:
        body = "speaker volume %d%%, voice %s." % (st.vol, "on" if st.voice_on else "off")
    elif i == CHIP:
        body = "ESP32-S3 rev %d.%d, 2 cores at %d MHz, MAC %s, ESP-IDF %s." % (
            st.chip_rev // 100, st.chip_rev % 100, st.cpu_mhz, st.mac, st.idf)
    elif i == STATUS:
        body = "battery %s about %d%%, chip %s C, free RAM %d KB, %s, screen %d%%, volume %d%%, up %s." % (
            _volts(st.bat_mv), st.bat_pct, _tenths(st.temp_c10), st.heap_kb, _sd_short(st), st.bright, st.vol,
            _uptime(st.uptime_s))
    elif i == LED_SET:
        if st.led == 0:
            body = "RGB LED off."
        else:
            body = "RGB LED set to %s." % COLORS[st.led]
            if st.bright_raised:
                body += " Screen brightness raised to 100%, because the LED shares its power with the backlight."
    elif i == BRIGHT_SET:
        body = ("brightness not changed, give a level from 10 to 100%." if st.new_bright < 0 else
                "screen brightness set to %d%% (was %d%%)." % (st.new_bright, st.bright))
    elif i == VOL_SET:
        body = ("volume not changed, give a level from 0 to 100%." if st.new_vol < 0 else
                "speaker volume set to %d%% (was %d%%)." % (st.new_vol, st.vol))
    elif i == BEEP:
        body = "played a %d Hz beep for %d ms." % (st.beep_hz, st.beep_ms)
    elif i == IR_SEND:
        if r.ir_addr < 0 or r.ir_cmd < 0:
            body = "IR not sent, give an address and a command, for example send ir address 4 command 8."
        elif r.ir_addr > 255 or r.ir_cmd > 255:
            body = "IR not sent, address and command must be 0 to 255."
        else:
            body = "IR sent NEC address 0x%02X command 0x%02X from G44." % (r.ir_addr, r.ir_cmd)
    else:
        return None
    return "Device: " + body


def _size_kb(kb):
    t = (kb * 10 + 512) // 1024
    return "%d.%d MB" % (t // 10, t % 10) if kb >= 1024 else "%d KB" % kb


# ------------------------------------------------------------------ fixed example (host test + verify)
def example_status() -> DevStatus:
    """Same values as dev_example() in device.c."""
    return DevStatus(bat_mv=3921, bat_pct=78, temp_c10=415, heap_kb=44, block_kb=31, flash_mb=8, model_kb=4818,
                     ctx_len=355, sd_type=3, sd_total_mb=15193, sd_used_mb=2150, mic_dbfs=-47, wifi_ok=1,
                     wifi_n=6, wifi_ssid="HomeNet", wifi_rssi=-48, wifi_ch=6, grove=[0x44, 0x76],
                     uptime_s=4980, bright=100, vol=50, voice_on=1, chip_rev=2, cpu_mhz=240,
                     mac="34:85:18:7A:2C:90", idf="v4.4.7")


# ------------------------------------------------------------------ simulation (training data only)
SSIDS = ["HomeNet", "TP-Link_4F2A", "SINGTEL-8C21", "StarHub_5G", "MyRepublic-1E", "Wireless@SG", "OfficeWiFi",
         "Lab-2.4G", "AndroidAP", "iPhone", "M1-Fibre-77", "ASUS_RT", "Guest", "xfinity", "Workshop", "eduroam"]


def simulate(rng: random.Random) -> DevStatus:
    st = example_status()
    pct = rng.choice([rng.randint(0, 100), rng.randint(60, 100), rng.randint(0, 20)])
    st.bat_pct = pct
    st.bat_mv = 3300 + pct * 9 + rng.randint(-15, 15) if pct < 100 else rng.randint(4150, 4250)
    st.temp_c10 = rng.randint(280, 620)
    st.heap_kb = rng.randint(20, 160)
    st.block_kb = max(8, st.heap_kb - rng.randint(5, 40))
    st.model_kb = rng.choice([2706, 4818])
    st.ctx_len = rng.choice([240, 288, 355, 400, 512])
    if rng.random() < 0.2:
        st.sd_type, st.sd_total_mb, st.sd_used_mb = 0, 0, 0
    else:
        st.sd_type = rng.choice([2, 3, 3, 3])
        st.sd_total_mb = rng.choice([1907, 3781, 7580, 15193, 30436, 60872, 121741])
        st.sd_used_mb = rng.randint(1, st.sd_total_mb)
    st.mic_dbfs = rng.randint(-72, -8)
    st.wifi_ok = 0 if rng.random() < 0.1 else 1
    st.wifi_n = rng.choice([0, rng.randint(1, 3), rng.randint(3, 20)])
    st.wifi_ssid = rng.choice(SSIDS)
    st.wifi_rssi = rng.randint(-90, -35)
    st.wifi_ch = rng.choice([1, 6, 11, rng.randint(1, 13)])
    k = rng.choice([0, 0, 1, 1, 2, 3])
    st.grove = sorted(rng.sample(list(I2C_NAMES) + [0x1F, 0x51, 0x5F], k))
    st.uptime_s = rng.choice([rng.randint(5, 59), rng.randint(60, 3599), rng.randint(3600, 86399),
                              rng.randint(86400, 400000)])
    st.bright = rng.choice([100, 100, 100, rng.randrange(10, 101, 10)])
    st.vol = rng.choice([50, rng.randrange(0, 101, 10)])
    st.voice_on = rng.choice([0, 1, 1])
    st.chip_rev = rng.choice([0, 1, 2])
    st.mac = "34:85:18:%02X:%02X:%02X" % (rng.randrange(256), rng.randrange(256), rng.randrange(256))
    st.idf = rng.choice(["v4.4.7", "v5.1.4", "v5.3.1"])
    return st


# ------------------------------------------------------------------ script hints
SEC_UNITS = {"s", "sec", "secs", "second", "seconds"}
MIN_UNITS = {"m", "min", "mins", "minute", "minutes"}
MAX_HINTS = 4


def script_hints(text: str) -> str:
    """Number conversions for a script request, so the model only copies them:
    '3 seconds' -> '3 s = 3000 ms.', '2 minutes' -> '2 min = 120000 ms = repeat 2 { wait 60000 }.', '0.5s' -> '0.5 s = 500 ms.',
    'half a second' -> '0.5 s = 500 ms.', '0x20' -> '0x20 = 32.'  Twin of script_hints() in device.c."""
    t = text.lower()
    out, i, n = [], 0, len(t)
    while i < n and len(out) < MAX_HINTS:
        c = t[i]
        prev_alnum = i > 0 and (t[i - 1].isalnum() or t[i - 1] == ".")
        if c.isdigit() and not prev_alnum:
            if c == "0" and i + 2 < n and t[i + 1] == "x" and t[i + 2] in "0123456789abcdef":
                j = i + 2
                while j < n and t[j] in "0123456789abcdef":
                    j += 1
                if j - i <= 6 and (j >= n or not t[j].isalnum()):
                    out.append("%s = %d." % (t[i:j], int(t[i + 2:j], 16)))
                i = j
                continue
            j = i
            while j < n and t[j].isdigit():
                j += 1
            k = j
            if k + 1 < n and t[k] == "." and t[k + 1].isdigit():
                k += 1
                while k < n and t[k].isdigit():
                    k += 1
            num = t[i:k]
            m = k
            while m < n and t[m] == " ":
                m += 1
            e = m
            while e < n and "a" <= t[e] <= "z":
                e += 1
            unit = t[m:e]
            if j - i <= 6 and k - j <= 4:
                ip = int(t[i:j])
                frac = t[j + 1:k] if k > j else ""
                fv = int((frac + "000")[:3]) if frac else 0  # thousandths
                if unit in SEC_UNITS:
                    out.append("%s s = %d ms." % (num, ip * 1000 + fv))
                elif unit in MIN_UNITS:
                    ms = ip * 60000 + fv * 60
                    if 60000 < ms <= 600000 and ms % 60000 == 0:  # one wait is at most 60000 ms
                        out.append("%s min = %d ms = repeat %d { wait 60000 }." % (num, ms, ms // 60000))
                    else:
                        out.append("%s min = %d ms." % (num, ms))
            i = k
            continue
        if t.startswith("half a second", i) and not prev_alnum:
            out.append("0.5 s = 500 ms.")
            i += 13
            continue
        i += 1
    return " ".join(out)
