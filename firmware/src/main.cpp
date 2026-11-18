// CardMind for M5Stack Cardputer (ESP32-S3, 8 MB flash, no PSRAM): "Card", an assistant that reads
// the Cardputer's sensors, controls its LED / screen / speaker / IR (hw.cpp), and answers from its manual.
//
// Boot:  SD /espllm/model.bin --(copied if changed)--> flash partition "model" --mmap--> engine
//        SD /espllm/kb.bin is searched per question (BM25), never loaded into RAM.
// Keys:  type, Enter = send, Del = backspace.
// Commands: /new  /mute  /talk  /vol 0-255  /speed 40-120  /help
// Scripts:  Card answers "Script: ..." for repeated / timed / conditional requests; Enter runs it.
//           /do SCRIPT  /save NAME  /run NAME  /scripts   (saved in /espllm/scripts on the SD card)
#include <M5Cardputer.h>
#include <SD.h>
#include <SPI.h>
#include <esp_heap_caps.h>
#include <esp_idf_version.h>
#include <esp_partition.h>
#if ESP_IDF_VERSION_MAJOR < 5
#include <esp_spi_flash.h>
#endif

#include "chat.h"
#include "engine.h"
#include "hw.h"
#include "logo.h"
#include "kb.h"
#include "script.h"
#include "tokenizer.h"
#include "tts.h"

// Cardputer microSD (SPI) pins
#define SD_SCK 40
#define SD_MISO 39
#define SD_MOSI 14
#define SD_CS 12

static const char *SD_MODEL = "/espllm/model.bin";   // Arduino FS path
static const char *KB_VFS = "/sd/espllm/kb.bin";     // stdio path (SD is mounted at /sd)
static const char *BOT_NAME = "Card";
static const int INPUT_MAX_CHARS = 200;
static const int CONSOLE_H = 119;

static M5Canvas console(&M5Cardputer.Display);
static Engine engine;
static Tokenizer tok;
static KB kb;
static Chat chat;
static String input;
static bool ready = false;

// ---------------------------------------------------------------- display
static void con_print(const char *s, int n = -1) {
    if (n < 0) console.print(s);
    else for (int i = 0; i < n; i++) console.print(s[i]);
    console.pushSprite(0, 0);
}

static void draw_input() {
    auto &d = M5Cardputer.Display;
    d.fillRect(0, CONSOLE_H, d.width(), d.height() - CONSOLE_H, TFT_DARKGREY);
    d.setTextColor(TFT_WHITE, TFT_DARKGREY);
    String shown = "> " + input;
    const int max_chars = 28;  // keep the end of long input visible
    if ((int)shown.length() > max_chars) shown = "<" + shown.substring(shown.length() - (max_chars - 1));
    d.drawString(shown + "_", 2, CONSOLE_H + 1);
}

static void fatal(const char *msg) {
    con_print("\n[error] ");
    con_print(msg);
    for (;;) delay(1000);
}

// ---------------------------------------------------------------- model partition
static const esp_partition_t *model_partition() {
    return esp_partition_find_first(ESP_PARTITION_TYPE_DATA, (esp_partition_subtype_t)0x40, "model");
}

// Copy model.bin from SD into flash if the SD copy differs. The first sector is written last,
// so an interrupted copy leaves no valid header and simply repeats on the next boot.
static void sync_model_from_sd(const esp_partition_t *part) {
    File f = SD.open(SD_MODEL, FILE_READ);
    if (!f) return;
    static uint8_t buf[4096];
    ModelHeader hs;
    if (f.read(buf, 256) != 256 || model_parse_header(buf, 256, &hs) != 0) { f.close(); con_print("SD model.bin invalid\n"); return; }
    if (hs.total_size > part->size || f.size() < hs.total_size) { f.close(); con_print("model.bin too big for partition\n"); return; }
    uint8_t cur[64];
    esp_partition_read(part, 0, cur, sizeof(cur));
    if (memcmp(cur, buf, sizeof(cur)) == 0) { f.close(); return; }  // same version already in flash

    con_print("Copying model to flash...\n");
    size_t total = hs.total_size, erase = (total + 4095) & ~(size_t)4095;
    if (esp_partition_erase_range(part, 0, erase) != ESP_OK) { f.close(); fatal("flash erase failed"); }
    int last_pct = -1;
    for (size_t off = 4096; off < total; off += sizeof(buf)) {
        size_t n = total - off < sizeof(buf) ? total - off : sizeof(buf);
        f.seek(off);
        if (f.read(buf, n) != (int)n || esp_partition_write(part, off, buf, n) != ESP_OK) { f.close(); fatal("model copy failed"); }
        int pct = (int)(100 * off / total);
        if (pct / 10 != last_pct / 10) { char m[16]; snprintf(m, sizeof(m), "%d%% ", pct); con_print(m); last_pct = pct; }
    }
    size_t n = total < 4096 ? total : 4096;
    f.seek(0);
    if (f.read(buf, n) != (int)n || esp_partition_write(part, 0, buf, n) != ESP_OK) { f.close(); fatal("model copy failed"); }
    f.close();
    con_print("done\n");
}

static const void *map_model(const esp_partition_t *part, size_t *size) {
    uint8_t hdr[256];
    ModelHeader h;
    if (esp_partition_read(part, 0, hdr, sizeof(hdr)) != ESP_OK || model_parse_header(hdr, sizeof(hdr), &h) != 0) return nullptr;
    const void *ptr = nullptr;
#if ESP_IDF_VERSION_MAJOR >= 5
    esp_partition_mmap_handle_t handle;
    if (esp_partition_mmap(part, 0, h.total_size, ESP_PARTITION_MMAP_DATA, &ptr, &handle) != ESP_OK) return nullptr;
#else
    spi_flash_mmap_handle_t handle;
    if (esp_partition_mmap(part, 0, h.total_size, SPI_FLASH_MMAP_DATA, &ptr, &handle) != ESP_OK) return nullptr;
#endif
    *size = h.total_size;
    return ptr;
}

// ---------------------------------------------------------------- RAM for Wi-Fi scans
// Wi-Fi needs more heap than is left beside the KV cache, so hw.cpp frees the engine for a scan.
// The chat restarts (the KV cache is gone); the engine comes back with the same context if it fits.
static const void *g_model;
static size_t g_model_size;
static int g_ctx;

static void ram_release() {
    engine_free(&engine);
    chat_new(&chat);
}

static int ram_restore() {
    for (int c = g_ctx; c >= 192; c -= 32)
        if (engine_init(&engine, g_model, g_model_size, c) == 0) { g_ctx = c; return c; }
    fatal("engine re-init failed after Wi-Fi scan (RAM?)");
    return 0;
}

// ---------------------------------------------------------------- chat callbacks
// A reply that starts with "Script:" is a Card script: it is shown, not spoken, and runs after Enter.
static char g_reply[512];
static int g_reply_len;
static int g_reply_kind;  // 0 undecided, 1 normal (spoken), 2 script

static void on_piece(const char *p, int n, void *) {
    con_print(p, n);
    if (g_reply_len + n < (int)sizeof(g_reply)) {
        memcpy(g_reply + g_reply_len, p, (size_t)n);
        g_reply_len += n;
        g_reply[g_reply_len] = 0;
    }
    if (g_reply_kind == 1) { tts_feed(p, n); return; }
    if (g_reply_kind == 2) return;
    const char *r = g_reply;
    while (*r == ' ') r++;
    int k = 0, plen = (int)strlen(SCRIPT_PREFIX);
    while (k < plen && r[k] && r[k] == SCRIPT_PREFIX[k]) k++;
    if (k == plen) g_reply_kind = 2;
    else if (r[k]) { g_reply_kind = 1; tts_feed(g_reply, g_reply_len); }  // not a script: speak what was held back
}
static void on_tick(void *) { vTaskDelay(1); }  // let the RTOS breathe between forward passes

static void say(const char *s) {
    con_print(s);
    tts_feed(s, strlen(s));
    tts_flush();
}

// ---------------------------------------------------------------- Card scripts
static const char *SCRIPT_DIR = "/espllm/scripts";
static const char *const UNITS[SR_N] = {"%", " C", " dBFS", " KB", " s", "%", "%"};
static Script g_script;                     // last script, waiting for Enter or being run
static bool g_pending = false;
static char g_last[SCRIPT_MAX_CHARS + 64];  // last valid script, canonical text (for /save)
static bool g_sd = false;

static bool key_pressed() {  // any new key press stops a running script
    M5Cardputer.update();
    return M5Cardputer.Keyboard.isChange() && M5Cardputer.Keyboard.isPressed();
}

static int s_read(int r, void *) { return hw_read(r); }

static int s_act(const SNode *n, void *) {
    switch (n->kind) {
    case SK_LED: hw_led((int)n->a); break;
    case SK_BRIGHT: hw_bright((int)n->a); break;
    case SK_VOL: hw_vol((int)n->a); break;
    case SK_BEEP: hw_beep((int)n->a, (int)n->b); break;
    case SK_IR: hw_ir((int)n->a, (int)n->b); break;
    case SK_WAIT:
        for (uint32_t t0 = millis(); millis() - t0 < (uint32_t)n->a;) {
            if (key_pressed()) return 1;
            delay(10);
        }
        return 0;
    }
    return key_pressed() ? 1 : 0;
}

static int s_show(int r, int v, void *) {
    char m[48];
    snprintf(m, sizeof(m), "%s %d%s\n", SCRIPT_READINGS[r], v, UNITS[r]);
    con_print(m);
    return key_pressed() ? 1 : 0;
}

static void run_script(const Script *sc) {
    con_print("(running, any key stops)\n");
    tts_stop();
    ScriptIO io = {s_read, s_act, s_show, nullptr, nullptr};
    uint32_t t0 = millis();
    int stopped = script_run(sc, &io);
    char m[48];
    if (stopped) snprintf(m, sizeof(m), "(stopped)\n");
    else snprintf(m, sizeof(m), "(done in %.1f s)\n", (millis() - t0) / 1000.0);
    con_print(m);
}

// Parses a script; prints the error and returns false if it is not valid.
static bool load_script(const char *text, Script *sc) {
    char err[64];
    if (script_parse(text, sc, err, sizeof(err))) {
        char m[96];
        snprintf(m, sizeof(m), "(script error: %s)\n", err);
        con_print(m);
        return false;
    }
    script_text(sc, g_last, sizeof(g_last));
    return true;
}

static bool valid_name(const String &n) {
    if (!n.length() || n.length() > 16) return false;
    for (unsigned i = 0; i < n.length(); i++) {
        char c = n[i];
        if (!isalnum((unsigned char)c) && c != '_' && c != '-') return false;
    }
    return true;
}

static void script_command(const String &cmd) {
    char m[96];
    if (cmd.startsWith("/do ")) {  // run a script you typed yourself
        con_print("\n");
        if (load_script(cmd.substring(4).c_str(), &g_script)) run_script(&g_script);
        return;
    }
    if (!g_sd) { con_print("\n(no SD card: scripts cannot be saved)\n"); return; }
    if (cmd == "/scripts") {
        File d = SD.open(SCRIPT_DIR);
        con_print("\n");
        int n = 0;
        if (d) {
            for (File f = d.openNextFile(); f; f = d.openNextFile()) {
                String name = f.name();
                int slash = name.lastIndexOf('/');
                if (slash >= 0) name = name.substring(slash + 1);
                if (name.endsWith(".txt")) { con_print((name.substring(0, name.length() - 4) + "  ").c_str()); n++; }
                f.close();
            }
            d.close();
        }
        con_print(n ? "\n" : "(no saved scripts; /save NAME after a script)\n");
        return;
    }
    int sp = cmd.indexOf(' ');
    String name = sp < 0 ? String("") : cmd.substring(sp + 1);
    name.trim();
    if (!valid_name(name)) { con_print("\n(name: up to 16 letters, digits, _ or -)\n"); return; }
    String path = String(SCRIPT_DIR) + "/" + name + ".txt";
    if (cmd.startsWith("/save")) {
        if (!g_last[0]) { con_print("\n(no script yet: ask Card for one, or /do ...)\n"); return; }
        SD.mkdir(SCRIPT_DIR);
        File f = SD.open(path, FILE_WRITE);
        if (!f) { con_print("\n(could not write to the SD card)\n"); return; }
        f.print(g_last);
        f.close();
        snprintf(m, sizeof(m), "\n(saved as %s)\n", name.c_str());
        con_print(m);
    } else {  // /run NAME
        File f = SD.open(path);
        if (!f) { snprintf(m, sizeof(m), "\n(no script called %s; /scripts lists them)\n", name.c_str()); con_print(m); return; }
        String text = f.readString();
        f.close();
        text.trim();
        con_print(("\n" + text + "\n").c_str());
        if (load_script(text.c_str(), &g_script)) run_script(&g_script);
    }
}

// Returns true if the text was a command.
static bool command(const String &cmd) {
    char m[64];
    if (cmd == "/new") { chat_new(&chat); con_print("\n(new chat)\n"); return true; }
    if (cmd == "/ctx") {  // what the model was given on the last turn (Device line, hints, card)
        con_print("\n[ctx] ");
        con_print(chat.ctx[0] ? chat.ctx : "-");
        con_print("\n");
        return true;
    }
    if (cmd == "/mute") { tts_set_enabled(false); con_print("\n(voice off)\n"); return true; }
    if (cmd == "/talk") { tts_set_enabled(true); con_print("\n"); say("Voice on!\n"); return true; }
    if (cmd.startsWith("/vol")) {
        tts_set_volume((uint8_t)constrain(cmd.substring(4).toInt(), 0, 255));
        snprintf(m, sizeof(m), "\n(volume %d)\n", tts_volume());
        con_print(m);
        if (tts_enabled()) say("Testing, one two three.\n");
        return true;
    }
    if (cmd.startsWith("/speed")) {
        tts_set_speed((uint8_t)constrain(cmd.substring(6).toInt(), 40, 120));
        snprintf(m, sizeof(m), "\n(speed %d, lower is faster)\n", tts_speed());
        con_print(m);
        if (tts_enabled()) say("Is this a good speed?\n");
        return true;
    }
    if (cmd == "/help") {
        con_print("\nAsk: battery, temperature, ram, sd card, noise, wifi, grove, uptime, status\n"
                  "Do: led red, dim the screen, volume 30, beep, send ir address 4 command 8\n"
                  "Script: blink the led 5 times, beep every 10 s, if battery < 20 beep\n"
                  "/do /save /run /scripts /new /ctx /mute /talk /vol /speed\n");
        return true;
    }
    if (cmd.startsWith("/do ") || cmd == "/scripts" || cmd.startsWith("/save") || cmd.startsWith("/run")) {
        script_command(cmd);
        return true;
    }
    return false;
}

static void submit() {
    String text = input;
    input = "";
    draw_input();
    text.trim();
    if (!text.length()) return;
    tts_stop();  // a new message interrupts the voice
    if (text.startsWith("/") && command(text)) return;
    con_print("\n> ");
    con_print(text.c_str());
    con_print("\n");
    con_print(BOT_NAME);
    con_print(": ");
    uint32_t t0 = millis();
    g_reply_len = 0;
    g_reply[0] = 0;
    g_reply_kind = 0;
    int n = chat_turn(&chat, text.c_str(), on_piece, nullptr);
    if (n < 0) con_print("(that message is too long)");
    if (g_reply_kind == 0) tts_feed(g_reply, g_reply_len);  // short reply, never decided
    tts_flush();
    Serial.printf("[%d tokens in %lu ms] ctx: %s\n", n, (unsigned long)(millis() - t0), chat.ctx[0] ? chat.ctx : "-");
    con_print("\n");
    if (g_reply_kind == 2) {
        const char *body = strstr(g_reply, SCRIPT_PREFIX) + strlen(SCRIPT_PREFIX);
        if (load_script(body, &g_script)) {
            g_pending = true;
            con_print("[Enter] run   [other key] cancel\n");
        }
    }
}

// ---------------------------------------------------------------- setup / loop
void setup() {
    auto cfg = M5.config();
    M5Cardputer.begin(cfg, true);  // true = enable keyboard
    Serial.begin(115200);
    auto &d = M5Cardputer.Display;
    // M5GFX >= 0.3 already sets the Cardputer up as 240x135 landscape; older versions need rotation 1.
    if (d.width() < d.height()) d.setRotation(1);
    d.setFont(&fonts::Font2);
    // Boot logo (logo.h, in flash, no RAM): shown for a moment, then the console takes over.
    d.fillScreen(TFT_WHITE);
    d.pushImage((d.width() - LOGO_W) / 2, (d.height() - LOGO_H) / 2, LOGO_W, LOGO_H,
                (const lgfx::rgb565_t *)LOGO_RGB565);
    delay(1500);
    d.fillScreen(TFT_BLACK);
    console.setColorDepth(1);  // 1-bit sprite: ~3.6 KB of RAM
    console.createSprite(d.width(), CONSOLE_H);
    console.createPalette();
    console.setPaletteColor(0, TFT_BLACK);
    console.setPaletteColor(1, TFT_GREENYELLOW);
    console.setFont(&fonts::Font2);
    console.setTextColor(1, 0);
    console.setTextWrap(true);
    console.setTextScroll(true);
    console.fillSprite(0);
    con_print("CardMind booting...\n");
    tts_begin();  // before sizing the KV cache, so its RAM is accounted for

    SPI.begin(SD_SCK, SD_MISO, SD_MOSI, SD_CS);
    bool sd_ok = SD.begin(SD_CS, SPI, 25000000);
    con_print(sd_ok ? "SD ok\n" : "no SD card\n");

    const esp_partition_t *part = model_partition();
    if (!part) fatal("no 'model' partition (check partitions.csv)");
    g_sd = sd_ok;
    if (sd_ok) sync_model_from_sd(part);
    size_t size = 0;
    const void *model = map_model(part, &size);
    if (!model) fatal("no model in flash. Put espllm/model.bin on the SD card.");

    ModelHeader h;
    model_parse_header(model, size, &h);
    if (tok_init(&tok, (const uint8_t *)model + h.tokenizer_offset) != 0) fatal("bad tokenizer");

    if (!(sd_ok && kb_open(&kb, KB_VFS) == 0)) { memset(&kb, 0, sizeof(kb)); con_print("no kb.bin: no knowledge cards\n"); }

    // Size the context to the RAM we actually have.
    size_t free_ram = heap_caps_get_free_size(MALLOC_CAP_8BIT | MALLOC_CAP_INTERNAL);
    // (A Wi-Fi scan does not need RAM kept free here: hw.cpp frees the engine during the scan.)
    size_t reserve = 40 * 1024 + engine_work_bytes(&h, h.max_seq) + sizeof(int) * (h.max_seq + 8);
    int ctx = free_ram > reserve ? (int)((free_ram - reserve) / engine_kv_bytes_per_pos(&h)) : 0;
    if (ctx > h.max_seq) ctx = h.max_seq;
    if (ctx < 192) fatal("not enough RAM for the model");
    if (engine_init(&engine, model, size, ctx) != 0) fatal("engine init failed (RAM?)");
    if (chat_init(&chat, &engine, &tok, kb.f ? &kb : nullptr, esp_random()) != 0) fatal("chat init failed");
    chat.tick = on_tick;
    chat.dev = hw_device;
    g_model = model;
    g_model_size = size;
    g_ctx = ctx;
    hw_init(size, ctx, sd_ok);
    hw_set_ram_hooks(ram_release, ram_restore);

    char m[96];
    snprintf(m, sizeof(m), "model %.1f MB, ctx %d, free RAM %u KB\n", size / 1e6, ctx,
             (unsigned)(heap_caps_get_free_size(MALLOC_CAP_8BIT | MALLOC_CAP_INTERNAL) / 1024));
    con_print(m);
    Serial.print(m);  // also log it, so RAM/ctx can be checked without looking at the screen
    char hello[96];
    snprintf(hello, sizeof(hello), "Hi, I'm %s. Ask about the Cardputer, or /help.\n", BOT_NAME);
    say(hello);
    ready = true;
    draw_input();
}

void loop() {
    M5Cardputer.update();
    if (!ready) return;
    if (M5Cardputer.Keyboard.isChange() && M5Cardputer.Keyboard.isPressed()) {
        Keyboard_Class::KeysState st = M5Cardputer.Keyboard.keysState();
        if (g_pending) {  // a script from Card is waiting: Enter runs it, any other key cancels
            g_pending = false;
            if (st.enter) run_script(&g_script);
            else con_print("(cancelled)\n");
            return;
        }
        for (auto ch : st.word)
            if ((int)input.length() < INPUT_MAX_CHARS && ch >= 32 && ch < 127) input += ch;
        if (st.del && input.length()) input.remove(input.length() - 1);
        draw_input();
        if (st.enter) submit();
    }
}
