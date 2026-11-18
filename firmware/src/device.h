// Device requests: which sensor to read or action to take, and the "Device:" line the model sees.
// Portable C (no hardware access). Mirror of pipeline/lib/devtext.py: keep the two identical.
// The Cardputer side (reading sensors, doing actions) is in hw.cpp.
#pragma once

#ifdef __cplusplus
extern "C" {
#endif

enum DevIntent {
    DEV_NONE, DEV_BATTERY, DEV_TEMP, DEV_MEMORY, DEV_SD, DEV_MIC, DEV_WIFI, DEV_GROVE, DEV_UPTIME,
    DEV_SCREEN, DEV_VOLUME, DEV_CHIP, DEV_STATUS,
    DEV_LED_SET, DEV_BRIGHT_SET, DEV_VOL_SET, DEV_BEEP, DEV_IR_SEND
};
#define DEV_ARG_NONE (-1)
#define DEV_ARG_UP (-2)
#define DEV_ARG_DOWN (-3)
#define DEV_MAX_ADDRS 8
#define DEV_N_COLORS 11
#define DEV_LINE_CHARS 320

typedef struct {
    int intent;
    int arg;       // percent, DEV_ARG_UP / DEV_ARG_DOWN, or LED colour index
    long ir_addr;  // -1 = not given
    long ir_cmd;
    int script;    // 1 = a Card script request (repeat / timing / condition words)
} DevReq;

typedef struct {
    int bat_mv, bat_pct;
    int temp_c10;  // chip temperature, tenths of a degree C
    int heap_kb, block_kb, flash_mb, model_kb, ctx_len;
    int sd_type;   // 0 none, 1 MMC, 2 SDSC, 3 SDHC
    int sd_total_mb, sd_used_mb;
    int mic_dbfs;
    int wifi_ok, wifi_n, wifi_rssi, wifi_ch;
    char wifi_ssid[33];
    int grove_n;
    int grove[DEV_MAX_ADDRS];
    long uptime_s;
    int bright, vol, voice_on;
    int chip_rev, cpu_mhz;
    char mac[18];
    char idf[16];
    // filled by dev_plan
    int new_bright, new_vol, led, bright_raised;
    int beep_hz, beep_ms;
} DevStatus;

extern const char *const DEV_COLORS[DEV_N_COLORS];
extern const unsigned long DEV_COLOR_RGB[DEV_N_COLORS];

void dev_parse(const char *text, DevReq *r);
void dev_plan(const DevReq *r, DevStatus *st);
// Writes "Device: ..." into out. Returns its length, or 0 if r->intent is DEV_NONE.
int dev_line(const DevReq *r, const DevStatus *st, char *out, int outsize);
void dev_example(DevStatus *st);
// Number conversions for a script request ("3 s = 3000 ms. 0x20 = 32."); returns length, 0 if none.
int dev_script_hints(const char *text, char *out, int outsize);  // fixed values, same as example_status() in devtext.py

#ifdef __cplusplus
}
#endif
