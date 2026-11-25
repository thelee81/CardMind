// PC build of the device code, for testing without hardware.
//
//   host_chat model.bin [kb.bin]               interactive chat (same code path as the Cardputer);
//                                              /status key=value ... sets the simulated device readings
//   host_chat --tok model.bin "text"           print token ids
//   host_chat --logits model.bin id id ...     print logits after feeding ids (batched like the device)
//   host_chat --calc "text"                    print calculator line or NONE
//   host_chat --script "text"                  print canonical script | trace, or ERROR msg
//   host_chat --dev "text"                     print "<intent> <Device: line>" for the example status, or "0 NONE"
//   host_chat --kb kb.bin "text"               print "<id> <score>"
//   host_chat --say "text"                     print the sentences SAM would speak
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../src/calc.h"
#include "../src/device.h"
#include "../src/script.h"
#include "../src/chat.h"
#include "../src/engine.h"
#include "../src/kb.h"
#include "../src/tokenizer.h"
#include "../src/tts_text.h"

static void *load_file(const char *path, size_t *size) {
    FILE *f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "cannot open %s\n", path); exit(1); }
    fseek(f, 0, SEEK_END);
    *size = (size_t)ftell(f);
    fseek(f, 0, SEEK_SET);
    void *buf = malloc(*size);
    if (!buf || fread(buf, 1, *size, f) != *size) { fprintf(stderr, "read failed\n"); exit(1); }
    fclose(f);
    return buf;
}

static void emit(const char *p, int n, void *u) { (void)u; fwrite(p, 1, (size_t)n, stdout); fflush(stdout); }

static void say_sentence(const char *s, void *u) {
    (void)u;
    char out[600];
    tts_normalize(s, out, sizeof(out));
    printf("[%s]\n  -> %s\n", s, out);
}

// One "key=value" status override (grove=68,118). Used by --dev and by /status in chat.
static void set_status(DevStatus *st, const char *kv) {
    char key[32];
    const char *eq = strchr(kv, '=');
    if (!eq || eq - kv >= (int)sizeof(key)) return;
    snprintf(key, sizeof(key), "%.*s", (int)(eq - kv), kv);
    const char *v = eq + 1;
    struct { const char *k; int *p; } ints[] = {
        {"bat_mv", &st->bat_mv}, {"bat_pct", &st->bat_pct}, {"temp_c10", &st->temp_c10},
        {"heap_kb", &st->heap_kb}, {"block_kb", &st->block_kb}, {"flash_mb", &st->flash_mb},
        {"model_kb", &st->model_kb}, {"ctx_len", &st->ctx_len}, {"sd_type", &st->sd_type},
        {"sd_total_mb", &st->sd_total_mb}, {"sd_used_mb", &st->sd_used_mb}, {"mic_dbfs", &st->mic_dbfs},
        {"wifi_ok", &st->wifi_ok}, {"wifi_n", &st->wifi_n}, {"wifi_rssi", &st->wifi_rssi},
        {"wifi_ch", &st->wifi_ch}, {"bright", &st->bright}, {"vol", &st->vol}, {"voice_on", &st->voice_on},
        {"chip_rev", &st->chip_rev}, {"cpu_mhz", &st->cpu_mhz},
        {"psram_kb", &st->psram_kb}, {"psram_total_kb", &st->psram_total_kb}, {"room_ok", &st->room_ok},
        {"room_c10", &st->room_c10}, {"room_rh", &st->room_rh}, {"clock_ok", &st->clock_ok}, {"year", &st->year},
        {"month", &st->month}, {"day", &st->day}, {"wday", &st->wday}, {"hour", &st->hour},
        {"minute", &st->minute}, {"radar_ok", &st->radar_ok}, {"radar_n", &st->radar_n},
        {"radar_dist", &st->radar_dist}, {"radar_angle", &st->radar_angle}, {"radar_speed", &st->radar_speed},
        {"radar_approach", &st->radar_approach}, {"phone_ok", &st->phone_ok}};
    for (size_t k = 0; k < sizeof(ints) / sizeof(ints[0]); k++)
        if (!strcmp(key, ints[k].k)) *ints[k].p = atoi(v);
    if (!strcmp(key, "uptime_s")) st->uptime_s = atol(v);
    if (!strcmp(key, "wifi_ssid")) snprintf(st->wifi_ssid, sizeof(st->wifi_ssid), "%s", v);
    if (!strcmp(key, "mac")) snprintf(st->mac, sizeof(st->mac), "%s", v);
    if (!strcmp(key, "idf")) snprintf(st->idf, sizeof(st->idf), "%s", v);
    if (!strcmp(key, "grove")) {
        st->grove_n = 0;
        for (const char *p = v; *p && st->grove_n < DEV_MAX_ADDRS;) {
            st->grove[st->grove_n++] = atoi(p);
            while (*p && *p != ',') p++;
            if (*p == ',') p++;
        }
    }
}

// Simulated device for chat: /status changes it, and actions change brightness / volume like hw.cpp.
static DevStatus g_dev;
static void host_dev(const DevReq *r, DevStatus *st, void *u) {
    (void)u;
    *st = g_dev;
    dev_plan(r, st);
    if (st->new_bright >= 0) g_dev.bright = st->new_bright;
    if (st->new_vol >= 0) g_dev.vol = st->new_vol;
}

// --script: canonical text and a trace with fixed readings (same as scripttext.check()).
static const int EXAMPLE_READINGS[SR_N] = {78, 41, -47, 44, 4980, 100, 50, 27, 61};
typedef struct { char out[4096]; int len, items; } Trace;
static void tr_add(Trace *t, const char *item) {
    if (t->items >= 40) return;
    t->len += snprintf(t->out + t->len, sizeof(t->out) - (size_t)t->len, "%s%s", t->items ? " / " : "", item);
    t->items++;
}
static int tr_read(int r, void *u) { (void)u; return EXAMPLE_READINGS[r]; }
static int tr_act(const SNode *n, void *u) { char d[48]; script_describe(n, d, sizeof(d)); tr_add((Trace *)u, d); return 0; }
static int tr_show(int r, int v, void *u) { char d[48]; snprintf(d, sizeof(d), "show %s=%d", SCRIPT_READINGS[r], v); tr_add((Trace *)u, d); return 0; }
static void tr_branch(int r, int v, int ok, void *u) {
    char d[48];
    snprintf(d, sizeof(d), "if %s=%d %s", SCRIPT_READINGS[r], v, ok ? "yes" : "no");
    tr_add((Trace *)u, d);
}

int main(int argc, char **argv) {
    const char *board = getenv("CARDMIND_BOARD");  // "rlcd": the Waveshare ESP32-S3-RLCD-4.2 matcher
    if (board && !strcmp(board, "rlcd")) dev_set_board(DEV_BOARD_RLCD);
    if (argc >= 3 && !strcmp(argv[1], "--calc")) {
        char out[256];
        puts(calc_line(argv[2], out, sizeof(out)) ? out : "NONE");
        return 0;
    }
    if (argc >= 3 && !strcmp(argv[1], "--script")) {
        static Script sc;
        static Trace tr;
        char err[64], text[1024];
        if (script_parse(argv[2], &sc, err, sizeof(err))) { printf("ERROR %s\n", err); return 0; }
        script_text(&sc, text, sizeof(text));
        ScriptIO io = {tr_read, tr_act, tr_show, tr_branch, &tr};
        script_run(&sc, &io);
        printf("%s | %s\n", text, tr.out);
        return 0;
    }
    if (argc >= 3 && !strcmp(argv[1], "--hints")) {  // script number hints (devtext.script_hints)
        char out[256];
        dev_script_hints(argv[2], out, sizeof(out));
        printf("%s\n", out);
        return 0;
    }
    if (argc >= 3 && !strcmp(argv[1], "--dev")) {
        DevReq r;
        DevStatus st;
        char out[DEV_LINE_CHARS];
        dev_parse(argv[2], &r);
        dev_example(&st);
        for (int a = 3; a < argc; a++) set_status(&st, argv[a]);  // optional overrides key=value
        dev_plan(&r, &st);
        printf("%d %d %s\n", r.intent, r.script, dev_line(&r, &st, out, sizeof(out)) ? out : "NONE");
        return 0;
    }
    if (argc >= 3 && !strcmp(argv[1], "--say")) {  // feed in small pieces, like streamed tokens
        TtsSplitter sp;
        tts_split_init(&sp, say_sentence, NULL);
        const char *s = argv[2];
        for (int n = (int)strlen(s), i = 0; i < n; i += 3) tts_split_feed(&sp, s + i, n - i < 3 ? n - i : 3);
        tts_split_flush(&sp);
        return 0;
    }
    if (argc >= 4 && !strcmp(argv[1], "--kb")) {
        KB kb;
        if (kb_open(&kb, argv[2])) { fprintf(stderr, "bad kb\n"); return 1; }
        float s;
        int id = kb_search(&kb, argv[3], &s);
        printf("%d %.4f\n", id, s);
        kb_close(&kb);
        return 0;
    }
    int mode = 0;  // 0 chat, 1 tok, 2 logits
    int a = 1;
    if (argc >= 2 && !strcmp(argv[1], "--tok")) { mode = 1; a = 2; }
    if (argc >= 2 && !strcmp(argv[1], "--logits")) { mode = 2; a = 2; }
    if (argc <= a) { fprintf(stderr, "usage: see host_main.c\n"); return 1; }

    size_t size;
    void *model = load_file(argv[a], &size);
    ModelHeader h;
    if (model_parse_header(model, size, &h)) { fprintf(stderr, "bad model.bin\n"); return 1; }
    Tokenizer tok;
    if (tok_init(&tok, (const uint8_t *)model + h.tokenizer_offset)) { fprintf(stderr, "bad tokenizer\n"); return 1; }

    if (mode == 1) {
        int ids[4096];
        int n = tok_encode(&tok, argc > a + 1 ? argv[a + 1] : "", ids, 4096);
        for (int i = 0; i < n; i++) printf(i ? " %d" : "%d", ids[i]);
        printf("\n");
        return 0;
    }
    Engine e;
    int rc = engine_init(&e, model, size, 0);
    if (rc) { fprintf(stderr, "engine_init failed %d\n", rc); return 1; }
    if (mode == 2) {
        int n = argc - a - 1;
        int *ids = (int *)malloc(sizeof(int) * (size_t)(n ? n : 1));
        for (int i = 0; i < n; i++) ids[i] = atoi(argv[a + 1 + i]);
        const float *lg = e.logits;
        for (int i = 0; i < n; i += ENGINE_BATCH) {
            int m = n - i < ENGINE_BATCH ? n - i : ENGINE_BATCH;
            lg = engine_forward(&e, ids + i, m, i);
        }
        for (int i = 0; i < h.vocab; i++) printf(i ? " %.6f" : "%.6f", lg[i]);
        printf("\n");
        return 0;
    }

    KB kb;
    int have_kb = argc > a + 1 && kb_open(&kb, argv[a + 1]) == 0;
    Chat chat;
    chat_init(&chat, &e, &tok, have_kb ? &kb : NULL, 12345);
    dev_example(&g_dev);
    chat.dev = host_dev;
    printf("model: %d layers, dim %d, vocab %d, ctx %d; kb: %s\n", h.n_layers, h.dim, h.vocab, e.ctx_len,
           have_kb ? "yes" : "no");
    char line[2048];
    for (;;) {
        printf("\nyou> ");
        fflush(stdout);
        if (!fgets(line, sizeof(line), stdin)) break;
        line[strcspn(line, "\r\n")] = 0;
        if (!strcmp(line, "/quit")) break;
        if (!strcmp(line, "/new")) { chat_new(&chat); puts("(new chat)"); continue; }
        if (!strncmp(line, "/status", 7)) {  // /status key=value key=value ... (simulated readings)
            dev_example(&g_dev);
            for (char *t = strtok(line + 7, " "); t; t = strtok(NULL, " ")) set_status(&g_dev, t);
            puts("(status set)");
            continue;
        }
        if (!line[0]) continue;
        printf("bot>");
        chat_turn(&chat, line, emit, NULL);
        printf("\n  [ctx] %s\n", chat.ctx[0] ? chat.ctx : "-");
    }
    return 0;
}
