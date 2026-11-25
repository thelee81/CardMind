// Device requests: which sensor to read or action to take, and the "Device:" line the model sees.
// Portable C (no hardware access). Mirror of pipeline/lib/devtext.py: keep the two identical.
// The Cardputer side (reading sensors, doing actions) is in hw.cpp; the Waveshare ESP32-S3-RLCD-4.2
// side is card.cpp in the RLCD Eyes project.
//
// Board: dev_set_board() picks the board the requests are for. DEV_BOARD_CARDPUTER (the default)
// behaves exactly as before boards existed; DEV_BOARD_RLCD adds room / clock / radar / phone /
// I2C-bus readings and sound / face actions, and its Device lines say what the board lacks.
#pragma once

#ifdef __cplusplus
extern "C" {
#endif

enum DevBoard { DEV_BOARD_CARDPUTER, DEV_BOARD_RLCD };
void dev_set_board(int board);
int dev_board(void);

enum DevIntent {
    DEV_NONE, DEV_BATTERY, DEV_TEMP, DEV_MEMORY, DEV_SD, DEV_MIC, DEV_WIFI, DEV_GROVE, DEV_UPTIME,
    DEV_SCREEN, DEV_VOLUME, DEV_CHIP, DEV_STATUS,
    DEV_LED_SET, DEV_BRIGHT_SET, DEV_VOL_SET, DEV_BEEP, DEV_IR_SEND,
    // RLCD board only
    DEV_ROOM, DEV_CLOCK, DEV_RADAR, DEV_PHONE, DEV_I2C,   // readings
    DEV_SOUND, DEV_FACE                                   // actions (arg = index into DEV_SOUNDS / DEV_FACES)
};
#define DEV_N_SOUNDS 11
#define DEV_N_FACES 10
extern const char *const DEV_SOUNDS[DEV_N_SOUNDS];  // names understood by soundPlay() on the RLCD
extern const char *const DEV_FACES[DEV_N_FACES];    // [0] "normal" = automatic; others are eyesForce() names
#define DEV_ARG_NONE (-1)
#define DEV_ARG_UP (-2)
#define DEV_ARG_DOWN (-3)
#define DEV_MAX_ADDRS 8
#define DEV_N_COLORS 11
#define DEV_LINE_CHARS 360

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
    int grove_n;                // I2C scan: the Grove port (Cardputer) or the board's I2C bus (RLCD)
    int grove[DEV_MAX_ADDRS];
    // RLCD board
    int psram_kb, psram_total_kb;           // free / total PSRAM
    int room_ok, room_c10, room_rh;         // SHTC3: tenths of a degree C, relative humidity %
    int clock_ok, year, month, day, wday, hour, minute;  // local time; wday 0 = Sunday
    int radar_ok, radar_n;                  // radar_ok: frames received from the HLK-LD2451
    int radar_dist, radar_angle, radar_speed, radar_approach;  // nearest target: m, degrees, km/h
    int phone_ok;                           // Chronos app connected over BLE
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
