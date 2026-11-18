// Cardputer hardware for device requests: reads sensors and carries out actions.
// The text side (which request, the "Device:" line) is portable C in device.c.
#pragma once
#include <stddef.h>

#include "device.h"

// Call once after the engine is set up. model_bytes / ctx_len are reported by "memory".
void hw_init(size_t model_bytes, int ctx_len, bool sd_ok);
// Wi-Fi scans: release() frees the model's RAM (and restarts the chat), restore() sets it up
// again and returns the new context length.
void hw_set_ram_hooks(void (*release)(), int (*restore)());
// chat_dev_fn: fill *st with readings, dev_plan(), then do the action.
void hw_device(const DevReq *r, DevStatus *st, void *user);

// Single actions and readings (Card scripts use these too). Readings: SR_* in script.h.
void hw_led(int color);       // index into DEV_COLORS; raises brightness to 100% if needed
void hw_bright(int pct);      // 10..100
void hw_vol(int pct);         // 0..100
void hw_beep(int hz, int ms);
void hw_ir(int addr, int cmd);
int hw_read(int reading);     // battery %, temp C, mic dBFS, ram KB, uptime s, bright %, vol %
