// Robot voice: SAM (Software Automatic Mouth) running on core 0, played through the
// Cardputer's speaker. The model keeps generating on core 1 while finished sentences are spoken.
#pragma once
#include <stdint.h>

void tts_begin();                        // after M5Cardputer.begin()
void tts_feed(const char *text, int n);  // streamed reply text
void tts_flush();                        // end of reply: speak whatever is left
void tts_stop();                         // drop queued speech and silence the speaker now
void tts_set_enabled(bool on);
bool tts_enabled();
void tts_set_volume(uint8_t v);          // 0..255
uint8_t tts_volume();
void tts_set_speed(uint8_t s);           // SAM speed: lower = faster (40..120, default 72)
uint8_t tts_speed();
