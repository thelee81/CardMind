#include "tts.h"

#include <AudioOutput.h>  // from ESP8266Audio (only the base class is used)
#include <ESP8266SAM.h>
#include <M5Cardputer.h>
#include <Preferences.h>

#include "tts_text.h"

// ---------------------------------------------------------------- voice settings
// SAM presets (speed, pitch, mouth, throat): SAM 72/64/128/128, Robot 92/60/190/190, Elf 72/64/110/160.
// Bolt: a bright, friendly robot.
static const uint8_t VOICE_PITCH = 58;   // lower number = higher voice
static const uint8_t VOICE_MOUTH = 150;
static const uint8_t VOICE_THROAT = 160;
static const int SPK_CHANNEL = 0;
static const int SAM_MAX_INPUT = 200;    // SAM's input buffer is small; longer text is split

struct Item {
    uint32_t gen;
    char text[TTS_SENTENCE_MAX + 1];
};

#ifndef VOICE_DEFAULT_ON
#define VOICE_DEFAULT_ON 1
#endif

static QueueHandle_t q;
static volatile uint32_t gen = 1;  // bumped by tts_stop(): stale sentences and samples are dropped
static volatile bool enabled = true;
static volatile uint8_t speed = 72;
static uint8_t volume = 160;
static TtsSplitter splitter;
static Preferences prefs;

// SAM writes one sample at a time; collect them into small buffers for M5Unified's speaker.
class SpeakerOut : public AudioOutput {
   public:
    uint32_t my_gen = 0;
    bool begin() override { n = 0; return true; }
    bool SetRate(int hz) override { rate = hz; return true; }
    bool SetBitsPerSample(int) override { return true; }
    bool SetChannels(int) override { return true; }
    bool ConsumeSample(int16_t sample[2]) override {
        if (my_gen != gen) return true;  // stopped: swallow the rest quickly
        buf[cur][n++] = sample[0];
        if (n == BUF) push();
        return true;
    }
    bool stop() override {
        if (n && my_gen == gen) push();
        n = 0;
        return true;
    }

   private:
    static const int BUF = 512;
    int16_t buf[3][BUF];  // one playing, one queued, one being filled
    int cur = 0, n = 0, rate = 22050;
    void push() {
        while (M5Cardputer.Speaker.isPlaying(SPK_CHANNEL) == 2 && my_gen == gen) vTaskDelay(1);
        if (my_gen == gen) M5Cardputer.Speaker.playRaw(buf[cur], n, rate, false, 1, SPK_CHANNEL, false);
        cur = (cur + 1) % 3;
        n = 0;
    }
};

static SpeakerOut out;

static void say_long(ESP8266SAM &sam, char *text) {
    // split at spaces into pieces SAM can take
    char *p = text;
    while (*p) {
        int len = strlen(p);
        if (len <= SAM_MAX_INPUT) { sam.Say(&out, p); return; }
        int cut = SAM_MAX_INPUT;
        while (cut > 0 && p[cut] != ' ') cut--;
        if (cut == 0) cut = SAM_MAX_INPUT;
        char saved = p[cut];
        p[cut] = 0;
        sam.Say(&out, p);
        p[cut] = saved;
        p += cut;
        while (*p == ' ') p++;
    }
}

static void tts_task(void *) {
    static ESP8266SAM sam;  // static: keep SAM's state off the task stack
    static char norm[TTS_SENTENCE_MAX * 4];
    Item it;
    for (;;) {
        if (xQueueReceive(q, &it, portMAX_DELAY) != pdTRUE) continue;
        if (it.gen != gen || !enabled) continue;
        if (tts_normalize(it.text, norm, sizeof(norm)) <= 0) continue;
        sam.SetSpeed(speed);
        sam.SetPitch(VOICE_PITCH);
        sam.SetMouth(VOICE_MOUTH);
        sam.SetThroat(VOICE_THROAT);
        out.my_gen = it.gen;
        say_long(sam, norm);
    }
}

static void on_sentence(const char *s, void *) {
    if (!enabled) return;
    Item it;
    it.gen = gen;
    strncpy(it.text, s, TTS_SENTENCE_MAX);
    it.text[TTS_SENTENCE_MAX] = 0;
    xQueueSend(q, &it, pdMS_TO_TICKS(50));  // queue full: drop rather than stall the model
}

void tts_begin() {
    prefs.begin("espllm", false);
    // VOICE_DEFAULT_ON=0 (platformio.ini) boots muted regardless of the saved setting; /talk still works.
    enabled = VOICE_DEFAULT_ON ? prefs.getBool("voice", true) : false;
    volume = prefs.getUChar("vol", 160);
    speed = prefs.getUChar("speed", 72);
    M5Cardputer.Speaker.begin();
    M5Cardputer.Speaker.setVolume(volume);
    tts_split_init(&splitter, on_sentence, nullptr);
    q = xQueueCreate(6, sizeof(Item));
    // core 0: the model runs in loop() on core 1
    xTaskCreatePinnedToCore(tts_task, "tts", 6144, nullptr, 2, nullptr, 0);
}

void tts_feed(const char *text, int n) { tts_split_feed(&splitter, text, n); }
void tts_flush() { tts_split_flush(&splitter); }

void tts_stop() {
    gen = gen + 1;
    xQueueReset(q);
    splitter.len = 0;
    splitter.ended = 0;
    M5Cardputer.Speaker.stop(SPK_CHANNEL);
}

void tts_set_enabled(bool on) {
    if (!on) tts_stop();
    enabled = on;
    prefs.putBool("voice", on);
}
bool tts_enabled() { return enabled; }

void tts_set_volume(uint8_t v) {
    volume = v;
    M5Cardputer.Speaker.setVolume(v);
    prefs.putUChar("vol", v);
}
uint8_t tts_volume() { return volume; }

void tts_set_speed(uint8_t s) {
    speed = s;
    prefs.putUChar("speed", s);
}
uint8_t tts_speed() { return speed; }
