// Conversation manager: builds <ctx>/<usr>/<bot> prompts, keeps the KV cache across turns,
// samples the reply. Mirror of the Chat class in pipeline/chat.py.
#pragma once
#include <stdint.h>

#include "device.h"
#include "engine.h"
#include "kb.h"
#include "tokenizer.h"

#ifdef __cplusplus
extern "C" {
#endif

#define CHAT_MAX_ANSWER 120
#define CHAT_TOP_K 40
#ifndef CHAT_TEMPERATURE
#define CHAT_TEMPERATURE 0.5f  // 0.5: tiny model copies facts better than at 0.7; 0.3 repeats itself
#endif
#define CHAT_CTX_CHARS 1024

typedef void (*chat_emit_fn)(const char *piece, int len, void *user);
typedef void (*chat_tick_fn)(void *user);  // called between forward passes (watchdog / UI)
// Reads the sensors a request needs into *st, calls dev_plan() and carries out any action.
// NULL: use dev_example() (PC build).
typedef void (*chat_dev_fn)(const DevReq *r, DevStatus *st, void *user);

typedef struct {
    Engine *e;
    const Tokenizer *tok;
    KB *kb;  // may be NULL
    int pos, pending;
    uint32_t rng;
    int *ids;
    int ids_cap;
    char ctx[CHAT_CTX_CHARS];  // what the model was shown on the last turn
    int calc_len;              // length of the device + calculator part of ctx (kept when the card is dropped)
    chat_tick_fn tick;
    void *tick_user;
    chat_dev_fn dev;
    void *dev_user;
} Chat;

int chat_init(Chat *c, Engine *e, const Tokenizer *t, KB *kb, uint32_t seed);
void chat_free(Chat *c);
void chat_new(Chat *c);
// Runs one turn. Returns number of reply tokens, or -1 on error.
int chat_turn(Chat *c, const char *user, chat_emit_fn emit, void *user_data);

#ifdef __cplusplus
}
#endif
