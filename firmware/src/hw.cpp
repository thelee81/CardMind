// Cardputer v1.1 hardware for device requests (see hw.h).
//
// Pins (Cardputer v1.1 manual): battery ADC G10, mic SPM1423 DAT G46 / CLK G43, speaker NS4168
// BCLK G41 / SDATA G42 / LRCLK G43, IR TX G44, Grove HY2.0-4P SDA G2 (yellow) / SCL G1 (white),
// RGB LED (WS2812) data G21, powered through G38 together with the LCD backlight.
#include "hw.h"

#include <M5Cardputer.h>
#include <SD.h>
#include <WiFi.h>
#include <Wire.h>
#include <esp_heap_caps.h>
#include <esp_mac.h>
#include <math.h>

#define DISABLE_CODE_FOR_RECEIVER  // IRremote: send only
#include <IRremote.hpp>

#include "script.h"
#include "tts.h"

#define IR_PIN 44
#define LED_PIN 21
#define GROVE_SDA 2
#define GROVE_SCL 1
#define WIFI_MIN_HEAP (64 * 1024)  // a Wi-Fi scan needs roughly this much free heap
#define MIC_RATE 16000

static size_t g_model_bytes;
static int g_ctx_len;
static bool g_sd_ok;
static bool g_ir_ready;

static void (*g_release)();
static int (*g_restore)();

void hw_set_ram_hooks(void (*release)(), int (*restore)()) {
    g_release = release;
    g_restore = restore;
}

void hw_init(size_t model_bytes, int ctx_len, bool sd_ok) {
    g_model_bytes = model_bytes;
    g_ctx_len = ctx_len;
    g_sd_ok = sd_ok;
}

static int pct_from_255(int v) { return (v * 100 + 127) / 255; }
static int pct_to_255(int p) { return (p * 255 + 50) / 100; }

static int mic_dbfs() {
    static int16_t buf[512];
    tts_stop();
    M5Cardputer.Speaker.end();  // the mic and the speaker share G43
    M5Cardputer.Mic.begin();
    double sum = 0;
    long n = 0;
    for (int chunk = 0; chunk < 18; chunk++) {  // ~0.58 s; the first chunks settle the filter
        if (!M5Cardputer.Mic.record(buf, 512, MIC_RATE)) break;
        while (M5Cardputer.Mic.isRecording()) vTaskDelay(1);
        if (chunk < 3) continue;
        long mean = 0;
        for (int i = 0; i < 512; i++) mean += buf[i];
        mean /= 512;
        for (int i = 0; i < 512; i++) { double s = buf[i] - mean; sum += s * s; }
        n += 512;
    }
    M5Cardputer.Mic.end();
    M5Cardputer.Speaker.begin();
    M5Cardputer.Speaker.setVolume(tts_volume());
    if (!n) return -90;
    double rms = sqrt(sum / n);
    int db = rms > 0 ? (int)lround(20.0 * log10(rms / 32768.0)) : -90;
    return db < -90 ? -90 : db > 0 ? 0 : db;
}

static void wifi_scan_inner(DevStatus *st);

static void wifi_scan(DevStatus *st) {
    st->wifi_ok = 0;
    st->wifi_n = 0;
    bool freed = false;
    if (heap_caps_get_free_size(MALLOC_CAP_8BIT | MALLOC_CAP_INTERNAL) < WIFI_MIN_HEAP && g_release && g_restore) {
        g_release();  // the KV cache holds most of the heap: free it for the scan
        freed = true;
    }
    Serial.printf("[wifi] free heap %u KB before scan%s\n",
                  (unsigned)(heap_caps_get_free_size(MALLOC_CAP_8BIT | MALLOC_CAP_INTERNAL) / 1024),
                  freed ? " (model RAM released)" : "");
    if (heap_caps_get_free_size(MALLOC_CAP_8BIT | MALLOC_CAP_INTERNAL) >= WIFI_MIN_HEAP) wifi_scan_inner(st);
    if (freed) {
        g_ctx_len = g_restore();
        st->ctx_len = g_ctx_len;
    }
}

static void wifi_scan_inner(DevStatus *st) {
    if (!WiFi.mode(WIFI_STA)) { WiFi.mode(WIFI_OFF); return; }
    int n = WiFi.scanNetworks(false, false);
    if (n >= 0) {
        st->wifi_ok = 1;
        st->wifi_n = n;
        int best = -1;
        for (int i = 0; i < n; i++) if (best < 0 || WiFi.RSSI(i) > WiFi.RSSI(best)) best = i;
        if (best >= 0) {
            String ssid = WiFi.SSID(best);
            snprintf(st->wifi_ssid, sizeof(st->wifi_ssid), "%s", ssid.length() ? ssid.c_str() : "(hidden)");
            st->wifi_rssi = WiFi.RSSI(best);
            st->wifi_ch = WiFi.channel(best);
        }
    }
    WiFi.scanDelete();
    WiFi.mode(WIFI_OFF);  // give the RAM back to the model
}

static void grove_scan(DevStatus *st) {
    st->grove_n = 0;
    Wire.begin(GROVE_SDA, GROVE_SCL, 100000);
    for (int a = 0x08; a <= 0x77 && st->grove_n < DEV_MAX_ADDRS; a++) {
        Wire.beginTransmission((uint8_t)a);
        if (Wire.endTransmission() == 0) st->grove[st->grove_n++] = a;
    }
    Wire.end();
}

static void read_basic(DevStatus *st) {
    st->bat_mv = M5Cardputer.Power.getBatteryVoltage();
    int lvl = M5Cardputer.Power.getBatteryLevel();
    st->bat_pct = lvl < 0 ? 0 : lvl > 100 ? 100 : lvl;
    st->temp_c10 = (int)lroundf(temperatureRead() * 10.0f);
    st->heap_kb = (int)(heap_caps_get_free_size(MALLOC_CAP_8BIT | MALLOC_CAP_INTERNAL) / 1024);
    st->block_kb = (int)(heap_caps_get_largest_free_block(MALLOC_CAP_8BIT | MALLOC_CAP_INTERNAL) / 1024);
    st->flash_mb = (int)(ESP.getFlashChipSize() / (1024 * 1024));
    st->model_kb = (int)(g_model_bytes / 1024);
    st->ctx_len = g_ctx_len;
    st->sd_type = 0;
    if (g_sd_ok) {
        uint8_t t = SD.cardType();
        st->sd_type = t == CARD_MMC ? 1 : t == CARD_SD ? 2 : t == CARD_SDHC ? 3 : 0;
        if (st->sd_type) {
            st->sd_total_mb = (int)(SD.cardSize() / (1024 * 1024));
            st->sd_used_mb = (int)(SD.usedBytes() / (1024 * 1024));
        }
    }
    st->uptime_s = (long)(millis() / 1000);
    st->bright = pct_from_255(M5Cardputer.Display.getBrightness());
    st->vol = pct_from_255(tts_volume());
    st->voice_on = tts_enabled() ? 1 : 0;
    esp_chip_info_t info;
    esp_chip_info(&info);
    st->chip_rev = info.revision;
    st->cpu_mhz = getCpuFrequencyMhz();
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    snprintf(st->mac, sizeof(st->mac), "%02X:%02X:%02X:%02X:%02X:%02X", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    snprintf(st->idf, sizeof(st->idf), "%s", esp_get_idf_version());
    char *dash = strchr(st->idf, '-');  // "v4.4.7-dirty" -> "v4.4.7"
    if (dash) *dash = 0;
    st->beep_hz = 2000;
    st->beep_ms = 200;
}

// ---------------------------------------------------------------- actions (also used by Card scripts)
void hw_bright(int pct) { M5Cardputer.Display.setBrightness(pct_to_255(pct)); }

void hw_vol(int pct) {
    tts_set_volume((uint8_t)pct_to_255(pct));
    M5Cardputer.Speaker.setVolume(tts_volume());
}

void hw_led(int color) {
    // The RGB LED is powered with the backlight (G38): it needs 100% brightness.
    if (color != 0 && pct_from_255(M5Cardputer.Display.getBrightness()) < 100) hw_bright(100);
    unsigned long rgb = DEV_COLOR_RGB[color];
    neopixelWrite(LED_PIN, (rgb >> 16 & 0xFF) / 4, (rgb >> 8 & 0xFF) / 4, (rgb & 0xFF) / 4);  // 1/4: still bright
}

void hw_beep(int hz, int ms) {
    tts_stop();
    M5Cardputer.Speaker.tone(hz, ms);
    delay(ms + 20);
}

void hw_ir(int addr, int cmd) {
    if (!g_ir_ready) { IrSender.begin(IR_PIN); g_ir_ready = true; }
    IrSender.sendNEC((uint16_t)addr, (uint8_t)cmd, 0);
}

int hw_read(int reading) {
    switch (reading) {
    case SR_BATTERY: { int l = M5Cardputer.Power.getBatteryLevel(); return l < 0 ? 0 : l > 100 ? 100 : l; }
    case SR_TEMP: return (int)lroundf(temperatureRead());
    case SR_MIC: return mic_dbfs();
    case SR_RAM: return (int)(heap_caps_get_free_size(MALLOC_CAP_8BIT | MALLOC_CAP_INTERNAL) / 1024);
    case SR_UPTIME: return (int)(millis() / 1000);
    case SR_BRIGHT: return pct_from_255(M5Cardputer.Display.getBrightness());
    case SR_VOL: return pct_from_255(tts_volume());
    }
    return 0;
}

void hw_device(const DevReq *r, DevStatus *st, void *) {
    memset(st, 0, sizeof(*st));
    read_basic(st);
    if (r->intent == DEV_MIC) st->mic_dbfs = mic_dbfs();
    if (r->intent == DEV_WIFI) wifi_scan(st);
    if (r->intent == DEV_GROVE) grove_scan(st);
    dev_plan(r, st);

    // actions
    if (st->new_bright >= 0) hw_bright(st->new_bright);
    if (st->new_vol >= 0) hw_vol(st->new_vol);
    if (r->intent == DEV_LED_SET && st->led >= 0) hw_led(st->led);
    if (r->intent == DEV_BEEP) hw_beep(st->beep_hz, st->beep_ms);
    if (r->intent == DEV_IR_SEND && r->ir_addr >= 0 && r->ir_cmd >= 0 && r->ir_addr <= 255 && r->ir_cmd <= 255)
        hw_ir((int)r->ir_addr, (int)r->ir_cmd);
}
