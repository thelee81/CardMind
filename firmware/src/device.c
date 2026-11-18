// Device requests and the "Device:" line. Mirror of pipeline/lib/devtext.py (keep identical).
#include "device.h"

#include <stdio.h>
#include <string.h>

#define MAX_WORDS 48
#define WORD_LEN 15

const char *const DEV_COLORS[DEV_N_COLORS] = {"off", "red", "green", "blue", "white", "yellow",
                                              "orange", "purple", "pink", "cyan", "magenta"};
const unsigned long DEV_COLOR_RGB[DEV_N_COLORS] = {0x000000, 0xFF0000, 0x00FF00, 0x0000FF, 0xFFFFFF, 0xFFFF00,
                                                   0xFF8000, 0x8000FF, 0xFF60A0, 0x00FFFF, 0xFF00FF};
static const char *const SD_TYPES[] = {"none", "MMC", "SDSC", "SDHC"};

static const struct { int addr; const char *name; } I2C_NAMES[] = {
    {0x23, "BH1750 light"}, {0x29, "VL53L0X distance"}, {0x38, "AHT20 temperature and humidity"},
    {0x3C, "SSD1306 OLED"}, {0x44, "SHT30 or SHT40 temperature and humidity"}, {0x48, "ADS1115 ADC"},
    {0x5A, "MLX90614 infrared thermometer"}, {0x62, "SCD40 CO2"}, {0x68, "MPU6886 IMU"},
    {0x70, "QMP6988 pressure"}, {0x76, "BMP280 pressure"}, {0x77, "BMP280 pressure"},
};

typedef struct { char w[MAX_WORDS][WORD_LEN + 1]; int n; } Words;

// ---------------------------------------------------------------- word sets (NULL-terminated)
static const char *const QUESTION_START[] = {"is", "are", "does", "do", "what", "whats", "which", "why", "when",
                                             "where", "who", "how", "did", "was", "were", "has", "have", "should",
                                             "will", NULL};
static const char *const HOWTO[] = {"code", "arduino", "sketch", "library", "function", "api", "example", "program",
                                    "programming", "uiflow", "uiflow2", "platformio", "micropython", "script",
                                    "wiring", "gpio", "pinout", "pin", "pins", "datasheet", "schematic", NULL};
static const char *const LED_NOUN[] = {"led", "rgb", "light", "lights", "lamp", "neopixel", "ws2812", NULL};
static const char *const LED_ON[] = {"on", "enable", "illuminate", "up", NULL};
static const char *const LED_OFF[] = {"kill", "disable", "dark", NULL};
static const char *const BRIGHT_NOUN[] = {"brightness", "backlight", "screen", "display", "lcd", NULL};
static const char *const VOL_NOUN[] = {"volume", "vol", "speaker", "voice", "sound", "audio", NULL};
static const char *const UP[] = {"up", "increase", "raise", "brighter", "brighten", "louder", "higher", "more", NULL};
static const char *const DOWN[] = {"down", "decrease", "lower", "reduce", "dim", "dimmer", "darker", "quieter",
                                   "softer", "less", NULL};
static const char *const SET_VERB[] = {"set", "turn", "make", "change", "put", "switch", "adjust", "go", NULL};
static const char *const BEEP_WORD[] = {"beep", "buzz", "buzzer", "chime", "ding", "tone", NULL};
static const char *const BEEP_NOUN[] = {"sound", "audio", "noise", NULL};
static const char *const BEEP_VERB[] = {"play", "make", "test", "emit", NULL};
static const char *const IR_NOUN[] = {"ir", "infrared", "remote", NULL};
static const char *const IR_VERB[] = {"send", "transmit", "fire", "emit", "blast", "press", NULL};
static const char *const MAX_W[] = {"max", "maximum", "full", "brightest", NULL};
static const char *const MUTE_W[] = {"mute", "silent", "silence", "off", "zero", NULL};
static const char *const LOUDER_W[] = {"louder", "quieter", "softer", NULL};
static const char *const ROOM_W[] = {"room", "here", "noise", NULL};
static const char *const SPK_W[] = {"speaker", "volume", NULL};
static const char *const GROVE_WEAK[] = {"plugged", "attached", "connected", NULL};
// Repetition / timing / conditions: the model writes a Card script instead of one instant action.
static const char *const SCRIPT_CUES[] = {"times", "twice", "thrice", "every", "repeat", "repeatedly", "loop", "blink",
                                          "blinking", "flashing", "strobe", "wait", "then", "after", "seconds",
                                          "second", "secs", "sec", "ms", "milliseconds", "minute", "minutes", "if",
                                          "when", "until", "while", "script", "instead", "cycle", "alternate",
                                          "sequence", "countdown", "forever", "fade", "fading", "ramp", "pulse",
                                          "pulsing", "police", "rainbow", "hz", NULL};

static const char *const W_STATUS[] = {"status", "overview", "summary", "everything", "diagnostic", "diagnostics",
                                       "health", "readings", NULL};
static const char *const W_BATTERY[] = {"battery", "batt", "charge", "charging", "charged", "voltage", "volt",
                                        "volts", NULL};
static const char *const W_TEMP[] = {"temperature", "temp", "hot", "warm", "heat", "overheating", "overheat",
                                     "celsius", "degrees", NULL};
static const char *const W_SD[] = {"sd", "microsd", "card", "storage", NULL};
static const char *const W_MIC[] = {"mic", "microphone", "noise", "noisy", "loud", "loudness", "decibel",
                                    "decibels", "db", "dbfs", "quiet", "hear", "listen", NULL};
static const char *const W_WIFI[] = {"wifi", "wlan", "network", "networks", "ssid", "router", "hotspot", "rssi",
                                     "internet", "signal", "signals", NULL};
static const char *const W_GROVE[] = {"grove", "i2c", "port", "unit", "units", "hy2", NULL};
static const char *const W_UPTIME[] = {"uptime", "boot", "booted", "running", NULL};
static const char *const W_MEMORY[] = {"ram", "mem", "memory", "heap", "psram", "flash", NULL};
static const char *const W_SCREEN[] = {"brightness", "backlight", "screen", "display", "lcd", NULL};
static const char *const W_VOLUME[] = {"volume", "vol", "speaker", NULL};
static const char *const W_CHIP[] = {"chip", "cpu", "processor", "mcu", "esp32", "esp32s3", "mac", "firmware",
                                     "idf", "mhz", "cores", NULL};
static const struct { int intent; const char *const *words; } READ_WORDS[] = {
    {DEV_STATUS, W_STATUS}, {DEV_BATTERY, W_BATTERY}, {DEV_TEMP, W_TEMP}, {DEV_SD, W_SD}, {DEV_MIC, W_MIC},
    {DEV_WIFI, W_WIFI}, {DEV_GROVE, W_GROVE}, {DEV_UPTIME, W_UPTIME}, {DEV_MEMORY, W_MEMORY},
    {DEV_SCREEN, W_SCREEN}, {DEV_VOLUME, W_VOLUME}, {DEV_CHIP, W_CHIP},
};

static int lower_alnum(char c, char *out) {
    if (c >= 'A' && c <= 'Z') c = (char)(c + 32);
    *out = c;
    return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9');
}

static void split(const char *text, Words *ws) {
    Words raw;
    raw.n = 0;
    char cur[WORD_LEN + 1];
    int k = 0, in = 0;
    for (const char *p = text;; p++) {
        char c = 0;
        int al = *p ? lower_alnum(*p, &c) : 0;
        if (al) {
            if (k < WORD_LEN) cur[k++] = c;
            in = 1;
        } else if (in) {
            cur[k] = 0;
            strcpy(raw.w[raw.n++], cur);
            k = 0;
            in = 0;
            if (raw.n >= MAX_WORDS) break;
        }
        if (!*p) break;
    }
    ws->n = 0;
    for (int i = 0; i < raw.n;) {
        if (i + 1 < raw.n && ((!strcmp(raw.w[i], "wi") && !strcmp(raw.w[i + 1], "fi")) ||
                              (!strcmp(raw.w[i], "micro") && !strcmp(raw.w[i + 1], "sd")))) {
            snprintf(ws->w[ws->n++], WORD_LEN + 1, "%s%s", raw.w[i], raw.w[i + 1]);
            i += 2;
        } else {
            strcpy(ws->w[ws->n++], raw.w[i]);
            i++;
        }
    }
}

static int in_list(const char *w, const char *const *list) {
    for (; *list; list++) if (!strcmp(w, *list)) return 1;
    return 0;
}
static int has(const Words *ws, const char *w) {
    for (int i = 0; i < ws->n; i++) if (!strcmp(ws->w[i], w)) return 1;
    return 0;
}
static int any(const Words *ws, const char *const *list) {
    for (int i = 0; i < ws->n; i++) if (in_list(ws->w[i], list)) return 1;
    return 0;
}

// Decimal (up to 9 digits) or 0x hex (up to 8 digits). Returns 1 and sets *v, or 0.
static int num(const char *w, long long *v) {
    int n = (int)strlen(w);
    if (n > 2 && w[0] == '0' && w[1] == 'x' && n <= 10) {
        long long x = 0;
        for (int i = 2; i < n; i++) {
            char c = w[i];
            int d = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : -1;
            if (d < 0) return 0;
            x = x * 16 + d;
        }
        *v = x;
        return 1;
    }
    if (n == 0 || n > 9) return 0;
    long long x = 0;
    for (int i = 0; i < n; i++) {
        if (w[i] < '0' || w[i] > '9') return 0;
        x = x * 10 + (w[i] - '0');
    }
    *v = x;
    return 1;
}

void dev_parse(const char *text, DevReq *r) {
    Words ws;
    split(text, &ws);
    r->intent = DEV_NONE;
    r->arg = DEV_ARG_NONE;
    r->ir_addr = -1;
    r->ir_cmd = -1;
    r->script = 0;
    if (!ws.n) return;
    int question = in_list(ws.w[0], QUESTION_START);
    int ir = any(&ws, IR_NOUN), howto = 0;
    for (int i = 0; i < ws.n && !howto; i++)  // "ir code" is not a how-to question
        if (in_list(ws.w[i], HOWTO) && !(ir && !strcmp(ws.w[i], "code"))) howto = 1;
    for (int i = 0; i + 1 < ws.n && !howto; i++)
        if (!strcmp(ws.w[i], "how") && (!strcmp(ws.w[i + 1], "to") || !strcmp(ws.w[i + 1], "do") ||
                                        !strcmp(ws.w[i + 1], "can") || !strcmp(ws.w[i + 1], "would") ||
                                        !strcmp(ws.w[i + 1], "should")))
            howto = 1;
    long long first_num = -1, v;
    for (int i = 0; i < ws.n; i++) if (num(ws.w[i], &v)) { first_num = v; break; }
    if (!question && any(&ws, SCRIPT_CUES)) { r->script = 1; return; }  // script request: ctx says "Mode: script."

    if (!question && !howto) {
        if (any(&ws, IR_NOUN) && any(&ws, IR_VERB)) {
            r->intent = DEV_IR_SEND;
            for (int i = 0; i + 1 < ws.n; i++) {
                if (!num(ws.w[i + 1], &v)) continue;
                if ((!strcmp(ws.w[i], "address") || !strcmp(ws.w[i], "addr")) && r->ir_addr < 0) r->ir_addr = v;
                else if ((!strcmp(ws.w[i], "command") || !strcmp(ws.w[i], "cmd") || !strcmp(ws.w[i], "code")) &&
                         r->ir_cmd < 0)
                    r->ir_cmd = v;
            }
            return;
        }
        if (any(&ws, LED_NOUN)) {
            for (int i = 0; i < DEV_N_COLORS; i++)
                if (has(&ws, DEV_COLORS[i])) { r->intent = DEV_LED_SET; r->arg = i; return; }
            if (any(&ws, LED_OFF)) { r->intent = DEV_LED_SET; r->arg = 0; return; }
            if (any(&ws, LED_ON)) { r->intent = DEV_LED_SET; r->arg = 4; return; }  // white
        }
        if (any(&ws, BEEP_WORD) || (any(&ws, BEEP_VERB) && any(&ws, BEEP_NOUN)) ||
            (has(&ws, "test") && has(&ws, "speaker")) || !strcmp(ws.w[0], "sound")) {
            r->intent = DEV_BEEP;
            return;
        }
        for (int k = 0; k < 2; k++) {
            const char *const *noun = k == 0 ? BRIGHT_NOUN : VOL_NOUN;
            int intent = k == 0 ? DEV_BRIGHT_SET : DEV_VOL_SET;
            if (!any(&ws, noun)) continue;
            if (first_num >= 0) { r->intent = intent; r->arg = first_num < 100 ? (int)first_num : 100; }
            else if (intent == DEV_BRIGHT_SET && any(&ws, MAX_W)) { r->intent = intent; r->arg = 100; }
            else if (intent == DEV_VOL_SET && any(&ws, MUTE_W)) { r->intent = intent; r->arg = 0; }
            else if (any(&ws, UP)) { r->intent = intent; r->arg = DEV_ARG_UP; }
            else if (any(&ws, DOWN)) { r->intent = intent; r->arg = DEV_ARG_DOWN; }
            else if (any(&ws, SET_VERB)) { r->intent = intent; r->arg = DEV_ARG_NONE; }
            if (r->intent) return;
        }
        if (has(&ws, "mute")) { r->intent = DEV_VOL_SET; r->arg = 0; return; }
        if (any(&ws, LOUDER_W) && !any(&ws, ROOM_W)) {
            r->intent = DEV_VOL_SET;
            r->arg = has(&ws, "louder") ? DEV_ARG_UP : DEV_ARG_DOWN;
            return;
        }
    }

    if (howto) return;  // pins, code, "how do I": a facts question, answered from the knowledge card
    int found[16], nf = 0;
    for (int k = 0; k < (int)(sizeof(READ_WORDS) / sizeof(READ_WORDS[0])); k++) {
        if (!any(&ws, READ_WORDS[k].words)) continue;
        if (READ_WORDS[k].intent == DEV_MIC && any(&ws, SPK_W)) continue;
        found[nf++] = READ_WORDS[k].intent;
    }
    if (!nf && any(&ws, GROVE_WEAK)) found[nf++] = DEV_GROVE;
    int has_uptime = 0, ti = -1, ci = -1;
    for (int k = 0; k < nf; k++) if (found[k] == DEV_UPTIME) has_uptime = 1;
    if (has(&ws, "how") && has(&ws, "long") && (has(&ws, "on") || has(&ws, "been")) && !has_uptime)
        found[nf++] = DEV_UPTIME;
    for (int k = 0; k < nf; k++) {
        if (found[k] == DEV_TEMP) ti = k;
        if (found[k] == DEV_CHIP) ci = k;
    }
    if (ti >= 0 && ci >= 0) {  // "chip temperature"
        for (int k = ci; k + 1 < nf; k++) found[k] = found[k + 1];
        nf--;
    }
    if (!nf) return;
    // "battery status" is the battery; "status" alone or 3+ topics is the status report
    int spec[16], ns = 0;
    for (int k = 0; k < nf; k++) if (found[k] != DEV_STATUS) spec[ns++] = found[k];
    r->intent = (!ns || ns >= 3) ? DEV_STATUS : spec[0];
}

static int clampi(int v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : v; }

void dev_plan(const DevReq *r, DevStatus *st) {
    st->new_bright = -1;
    st->new_vol = -1;
    st->led = -1;
    st->bright_raised = 0;
    if (r->intent == DEV_LED_SET) {
        st->led = r->arg;
        if (r->arg != 0 && st->bright < 100) { st->new_bright = 100; st->bright_raised = 1; }
    } else if (r->intent == DEV_BRIGHT_SET && r->arg != DEV_ARG_NONE) {
        int t = r->arg == DEV_ARG_UP ? st->bright + 20 : r->arg == DEV_ARG_DOWN ? st->bright - 20 : r->arg;
        st->new_bright = clampi(t, 10, 100);
    } else if (r->intent == DEV_VOL_SET && r->arg != DEV_ARG_NONE) {
        int t = r->arg == DEV_ARG_UP ? st->vol + 20 : r->arg == DEV_ARG_DOWN ? st->vol - 20 : r->arg;
        st->new_vol = clampi(t, 0, 100);
    }
}

// ---------------------------------------------------------------- formatting
static void volts(int mv, char *o, int n) { snprintf(o, (size_t)n, "%d.%02d V", mv / 1000, (mv % 1000) / 10); }
static void tenths(int v, char *o, int n) {
    snprintf(o, (size_t)n, "%s%d.%d", v < 0 ? "-" : "", (v < 0 ? -v : v) / 10, (v < 0 ? -v : v) % 10);
}
static void size_mb(int mb, char *o, int n) {
    long t = ((long)mb * 10 + 512) / 1024;
    if (mb >= 1024) snprintf(o, (size_t)n, "%ld.%ld GB", t / 10, t % 10);
    else snprintf(o, (size_t)n, "%d MB", mb);
}
static void size_kb(int kb, char *o, int n) {
    long t = ((long)kb * 10 + 512) / 1024;
    if (kb >= 1024) snprintf(o, (size_t)n, "%ld.%ld MB", t / 10, t % 10);
    else snprintf(o, (size_t)n, "%d KB", kb);
}
static void uptime(long s, char *o, int n) {
    long d = s / 86400, h = s / 3600 % 24, m = s / 60 % 60;
    if (d) snprintf(o, (size_t)n, "%ld d %ld h", d, h);
    else if (h) snprintf(o, (size_t)n, "%ld h %ld min", h, m);
    else if (m) snprintf(o, (size_t)n, "%ld min %ld s", m, s % 60);
    else snprintf(o, (size_t)n, "%ld s", s);
}
static const char *mic_label(int db) {
    return db <= -55 ? "very quiet" : db <= -40 ? "quiet" : db <= -25 ? "moderate" : "loud";
}

int dev_line(const DevReq *r, const DevStatus *st, char *out, int outsize) {
    char a[48], b[48], c[48], d[48];
    int len = 0;
    out[0] = 0;
#define P(...) (len += snprintf(out + len, len < outsize ? (size_t)(outsize - len) : 0, __VA_ARGS__))
    switch (r->intent) {
    case DEV_NONE: return 0;
    case DEV_BATTERY:
        volts(st->bat_mv, a, sizeof(a));
        P("Device: battery %s, about %d%%.", a, st->bat_pct);
        break;
    case DEV_TEMP:
        tenths(st->temp_c10, a, sizeof(a));
        P("Device: chip temperature %s C.", a);
        break;
    case DEV_MEMORY:
        size_kb(st->model_kb, a, sizeof(a));
        P("Device: free RAM %d KB, largest free block %d KB, no PSRAM, flash %d MB, model %s, context %d tokens.",
          st->heap_kb, st->block_kb, st->flash_mb, a, st->ctx_len);
        break;
    case DEV_SD:
        if (!st->sd_type) { P("Device: no SD card found."); break; }
        size_mb(st->sd_total_mb, a, sizeof(a));
        size_mb(st->sd_used_mb, b, sizeof(b));
        P("Device: SD card %s, %s, %s used.", SD_TYPES[st->sd_type], a, b);
        break;
    case DEV_MIC:
        P("Device: sound level %d dBFS (%s).", st->mic_dbfs, mic_label(st->mic_dbfs));
        break;
    case DEV_WIFI:
        if (!st->wifi_ok) P("Device: Wi-Fi scan failed, not enough free RAM.");
        else if (!st->wifi_n) P("Device: Wi-Fi scan found no networks.");
        else
            P("Device: Wi-Fi scan found %d network%s, strongest %s at %d dBm on channel %d.", st->wifi_n,
              st->wifi_n == 1 ? "" : "s", st->wifi_ssid, st->wifi_rssi, st->wifi_ch);
        break;
    case DEV_GROVE:
        if (!st->grove_n) { P("Device: Grove I2C scan (SDA G2, SCL G1) found nothing."); break; }
        P("Device: Grove I2C scan (SDA G2, SCL G1) found ");
        for (int k = 0; k < st->grove_n && k < DEV_MAX_ADDRS; k++) {
            const char *name = NULL;
            for (int j = 0; j < (int)(sizeof(I2C_NAMES) / sizeof(I2C_NAMES[0])); j++)
                if (I2C_NAMES[j].addr == st->grove[k]) name = I2C_NAMES[j].name;
            if (name) P("%s0x%02X (probably %s)", k ? ", " : "", st->grove[k], name);
            else P("%s0x%02X (unknown)", k ? ", " : "", st->grove[k]);
        }
        P(".");
        break;
    case DEV_UPTIME:
        uptime(st->uptime_s, a, sizeof(a));
        P("Device: up %s since boot.", a);
        break;
    case DEV_SCREEN: P("Device: screen brightness %d%%.", st->bright); break;
    case DEV_VOLUME: P("Device: speaker volume %d%%, voice %s.", st->vol, st->voice_on ? "on" : "off"); break;
    case DEV_CHIP:
        P("Device: ESP32-S3 rev %d.%d, 2 cores at %d MHz, MAC %s, ESP-IDF %s.", st->chip_rev / 100,
          st->chip_rev % 100, st->cpu_mhz, st->mac, st->idf);
        break;
    case DEV_STATUS:
        volts(st->bat_mv, a, sizeof(a));
        tenths(st->temp_c10, b, sizeof(b));
        uptime(st->uptime_s, c, sizeof(c));
        P("Device: battery %s about %d%%, chip %s C, free RAM %d KB, ", a, st->bat_pct, b, st->heap_kb);
        if (!st->sd_type) P("no SD card");
        else {
            size_mb(st->sd_total_mb, a, sizeof(a));
            size_mb(st->sd_used_mb, d, sizeof(d));
            P("SD card %s (%s used)", a, d);
        }
        P(", screen %d%%, volume %d%%, up %s.", st->bright, st->vol, c);
        break;
    case DEV_LED_SET:
        if (st->led == 0) { P("Device: RGB LED off."); break; }
        P("Device: RGB LED set to %s.", DEV_COLORS[st->led]);
        if (st->bright_raised)
            P(" Screen brightness raised to 100%%, because the LED shares its power with the backlight.");
        break;
    case DEV_BRIGHT_SET:
        if (st->new_bright < 0) P("Device: brightness not changed, give a level from 10 to 100%%.");
        else P("Device: screen brightness set to %d%% (was %d%%).", st->new_bright, st->bright);
        break;
    case DEV_VOL_SET:
        if (st->new_vol < 0) P("Device: volume not changed, give a level from 0 to 100%%.");
        else P("Device: speaker volume set to %d%% (was %d%%).", st->new_vol, st->vol);
        break;
    case DEV_BEEP: P("Device: played a %d Hz beep for %d ms.", st->beep_hz, st->beep_ms); break;
    case DEV_IR_SEND:
        if (r->ir_addr < 0 || r->ir_cmd < 0)
            P("Device: IR not sent, give an address and a command, for example send ir address 4 command 8.");
        else if (r->ir_addr > 255 || r->ir_cmd > 255) P("Device: IR not sent, address and command must be 0 to 255.");
        else P("Device: IR sent NEC address 0x%02X command 0x%02X from G44.", (int)r->ir_addr, (int)r->ir_cmd);
        break;
    default: return 0;
    }
#undef P
    return len < outsize ? len : outsize - 1;
}

void dev_example(DevStatus *st) {
    memset(st, 0, sizeof(*st));
    st->bat_mv = 3921; st->bat_pct = 78; st->temp_c10 = 415;
    st->heap_kb = 44; st->block_kb = 31; st->flash_mb = 8; st->model_kb = 4818; st->ctx_len = 355;
    st->sd_type = 3; st->sd_total_mb = 15193; st->sd_used_mb = 2150;
    st->mic_dbfs = -47;
    st->wifi_ok = 1; st->wifi_n = 6; strcpy(st->wifi_ssid, "HomeNet"); st->wifi_rssi = -48; st->wifi_ch = 6;
    st->grove_n = 2; st->grove[0] = 0x44; st->grove[1] = 0x76;
    st->uptime_s = 4980; st->bright = 100; st->vol = 50; st->voice_on = 1;
    st->chip_rev = 2; st->cpu_mhz = 240;
    strcpy(st->mac, "34:85:18:7A:2C:90");
    strcpy(st->idf, "v4.4.7");
    st->new_bright = -1; st->new_vol = -1; st->led = -1; st->bright_raised = 0;
    st->beep_hz = 2000; st->beep_ms = 200;
}

// ---------------------------------------------------------------- script hints
static int is_unit(const char *u, int len, const char *const *list) {
    for (; *list; list++) if ((int)strlen(*list) == len && !strncmp(u, *list, (size_t)len)) return 1;
    return 0;
}

int dev_script_hints(const char *text, char *out, int outsize) {
    static const char *const SEC[] = {"s", "sec", "secs", "second", "seconds", NULL};
    static const char *const MIN[] = {"m", "min", "mins", "minute", "minutes", NULL};
    char t[256];
    int n = 0, len = 0, hints = 0;
    while (text[n] && n < (int)sizeof(t) - 1) { char c = text[n]; t[n] = (c >= 'A' && c <= 'Z') ? (char)(c + 32) : c; n++; }
    t[n] = 0;
    out[0] = 0;
#define ISD(c) ((c) >= '0' && (c) <= '9')
#define ISL(c) ((c) >= 'a' && (c) <= 'z')
#define ISH(c) (ISD(c) || ((c) >= 'a' && (c) <= 'f'))
#define ADD(...) do { if (len < outsize) { int w_ = snprintf(out + len, (size_t)(outsize - len), __VA_ARGS__); if (w_ > 0) len += w_; } hints++; } while (0)
    for (int i = 0; i < n && hints < 4;) {
        char c = t[i];
        int prev_alnum = i > 0 && (ISD(t[i - 1]) || ISL(t[i - 1]) || t[i - 1] == '.');
        if (ISD(c) && !prev_alnum) {
            if (c == '0' && i + 2 < n && t[i + 1] == 'x' && ISH(t[i + 2])) {
                int j = i + 2;
                long v = 0;
                while (j < n && ISH(t[j])) { v = v * 16 + (ISD(t[j]) ? t[j] - '0' : t[j] - 'a' + 10); j++; }
                if (j - i <= 6 && (j >= n || !(ISD(t[j]) || ISL(t[j])))) ADD("%s%.*s = %ld.", hints ? " " : "", j - i, t + i, v);
                i = j;
                continue;
            }
            int j = i;
            while (j < n && ISD(t[j])) j++;
            int k = j;
            if (k + 1 < n && t[k] == '.' && ISD(t[k + 1])) { k++; while (k < n && ISD(t[k])) k++; }
            int m = k;
            while (m < n && t[m] == ' ') m++;
            int e = m;
            while (e < n && ISL(t[e])) e++;
            if (j - i <= 6 && k - j <= 4) {
                long ip = 0, fv = 0;
                for (int q = i; q < j; q++) ip = ip * 10 + (t[q] - '0');
                if (k > j) for (int q = 0; q < 3; q++) fv = fv * 10 + (j + 1 + q < k ? t[j + 1 + q] - '0' : 0);
                if (is_unit(t + m, e - m, SEC)) ADD("%s%.*s s = %ld ms.", hints ? " " : "", k - i, t + i, ip * 1000 + fv);
                else if (is_unit(t + m, e - m, MIN)) {
                    long ms = ip * 60000 + fv * 60;
                    if (ms > 60000 && ms <= 600000 && ms % 60000 == 0)  // one wait is at most 60000 ms
                        ADD("%s%.*s min = %ld ms = repeat %ld { wait 60000 }.", hints ? " " : "", k - i, t + i, ms, ms / 60000);
                    else
                        ADD("%s%.*s min = %ld ms.", hints ? " " : "", k - i, t + i, ms);
                }
            }
            i = k;
            continue;
        }
        if (!prev_alnum && !strncmp(t + i, "half a second", 13)) { ADD("%s0.5 s = 500 ms.", hints ? " " : ""); i += 13; continue; }
        i++;
    }
#undef ADD
#undef ISH
#undef ISL
#undef ISD
    return len < outsize ? len : outsize - 1;
}
