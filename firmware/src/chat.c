#include "chat.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "calc.h"

int chat_init(Chat *c, Engine *e, const Tokenizer *t, KB *kb, uint32_t seed) {
    memset(c, 0, sizeof(*c));
    c->e = e;
    c->tok = t;
    c->kb = kb;
    c->rng = seed ? seed : 0x9E3779B9u;
    c->ids_cap = e->ctx_len + 8;
    c->ids = (int *)malloc(sizeof(int) * (size_t)c->ids_cap);
    if (!c->ids) return -1;
    chat_new(c);
    return 0;
}

void chat_free(Chat *c) { free(c->ids); c->ids = NULL; }

void chat_new(Chat *c) {
    c->pos = 0;
    c->pending = -1;
}

static uint32_t xorshift(uint32_t *s) {
    uint32_t x = *s;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    return *s = x;
}

static int sample(Chat *c, const float *logits, int vocab) {
    int top[CHAT_TOP_K];
    float val[CHAT_TOP_K];
    int k = 0;
    for (int i = 0; i < vocab; i++) {  // keep the K largest, sorted descending
        float v = logits[i];
        if (k < CHAT_TOP_K) k++;
        else if (v <= val[k - 1]) continue;
        int j = k - 1;
        while (j > 0 && val[j - 1] < v) { val[j] = val[j - 1]; top[j] = top[j - 1]; j--; }
        val[j] = v;
        top[j] = i;
    }
    float p[CHAT_TOP_K], sum = 0.0f;
    for (int i = 0; i < k; i++) { p[i] = expf((val[i] - val[0]) / CHAT_TEMPERATURE); sum += p[i]; }
    float r = (float)(xorshift(&c->rng) >> 8) / 16777216.0f * sum;
    for (int i = 0; i < k; i++) { r -= p[i]; if (r <= 0.0f) return top[i]; }
    return top[k - 1];
}

// <ctx> text: device line, calculator line and/or best knowledge-base passage
// (same as build_ctx in kbtext.py)
static int build_ctx(Chat *c, const char *user) {
    int n = 0;
    c->ctx[0] = 0;
    DevReq r;
    dev_parse(user, &r);
    if (r.script) {  // a Card script request: the model writes one "Script:" line (no card, no calculator)
        snprintf(c->ctx, CHAT_CTX_CHARS, "%s", "Mode: script.");
        n = (int)strlen(c->ctx);
        char h[256];  // up to 4 hints of ~50 chars
        if (dev_script_hints(user, h, sizeof(h)) > 0 && n + 1 + (int)strlen(h) < CHAT_CTX_CHARS) {
            c->ctx[n++] = ' ';
            strcpy(c->ctx + n, h);
            n = (int)strlen(c->ctx);
        }
        c->calc_len = n;
        return n;
    }
    if (r.intent != DEV_NONE) {
        DevStatus st;
        if (c->dev) c->dev(&r, &st, c->dev_user);
        else { dev_example(&st); dev_plan(&r, &st); }
        n = dev_line(&r, &st, c->ctx, CHAT_CTX_CHARS);
    }
    if (n < CHAT_CTX_CHARS - 2) {
        char *p = c->ctx + n + (n ? 1 : 0);
        if (calc_line(user, p, CHAT_CTX_CHARS - n - 1)) {
            if (n) c->ctx[n] = ' ';
            n = (int)strlen(c->ctx);
        } else {
            c->ctx[n] = 0;
        }
    }
    c->calc_len = n;
    // With a Device line the knowledge card is left out: a long card distracts the model from the reading.
    if (c->kb && c->kb->f && r.intent == DEV_NONE) {
        float score;
        int id = kb_search(c->kb, user, &score);
        if (id >= 0 && score >= c->kb->min_score) {
            if (n && n < CHAT_CTX_CHARS - 2) c->ctx[n++] = ' ';
            int m = kb_passage(c->kb, id, c->ctx + n, CHAT_CTX_CHARS - n);
            if (m > 0) n += m;
            c->ctx[n] = 0;
        }
    }
    return n;
}

static int build_prompt(Chat *c, const char *user, int with_ctx, int *out, int cap) {
    const ModelHeader *h = &c->e->h;
    int n = 0;
    if (with_ctx && c->ctx[0] && n < cap) {
        out[n++] = h->ctx;
        n += tok_encode(c->tok, c->ctx, out + n, cap - n);
    }
    if (n < cap) out[n++] = h->usr;
    n += tok_encode(c->tok, user, out + n, cap - n - 1);
    out[n++] = h->bot;
    return n;
}

static const float *feed(Chat *c, const int *ids, int n) {
    const float *logits = c->e->logits;
    for (int i = 0; i < n; i += ENGINE_BATCH) {
        int m = n - i < ENGINE_BATCH ? n - i : ENGINE_BATCH;
        logits = engine_forward(c->e, ids + i, m, c->pos);
        c->pos += m;
        if (c->tick) c->tick(c->tick_user);
    }
    return logits;
}

int chat_turn(Chat *c, const char *user, chat_emit_fn emit, void *ud) {
    const ModelHeader *h = &c->e->h;
    const int L = c->e->ctx_len;
    build_ctx(c, user);
    int cap = c->ids_cap - 2;
    int *prompt = c->ids + 2;  // room for <bos> and pending <eot> in front
    int np = build_prompt(c, user, 1, prompt, cap);
    int extra = c->pending >= 0 ? 1 : 0;
    if (c->pos + extra + np + CHAT_MAX_ANSWER > L) {
        chat_new(c);  // out of room: forget the history, keep this question
        extra = 0;
        if (1 + np + CHAT_MAX_ANSWER > L) {  // still too long: drop the card, keep the calculator line
            c->ctx[c->calc_len] = 0;
            np = build_prompt(c, user, 1, prompt, cap);
        }
        if (1 + np + CHAT_MAX_ANSWER > L) {  // still too long: no ctx at all
            c->ctx[0] = 0;
            np = build_prompt(c, user, 0, prompt, cap);
            if (1 + np + CHAT_MAX_ANSWER > L) return -1;
        }
    }
    int *ids = prompt;
    int n = np;
    if (extra) { *--ids = c->pending; n++; }
    if (c->pos == 0) { *--ids = h->bos; n++; }
    c->pending = -1;
    const float *logits = feed(c, ids, n);

    int produced = 0;
    for (; produced < CHAT_MAX_ANSWER; produced++) {
        int t = sample(c, logits, h->vocab);
        if (t == h->eot || t == h->eos || c->pos >= L) break;
        int len;
        const char *piece = tok_piece(c->tok, t, &len);
        if (emit && len) emit(piece, len, ud);
        logits = feed(c, &t, 1);
    }
    c->pending = h->eot;  // fed at the start of the next turn
    return produced;
}
