#include "tokenizer.h"

#include <string.h>

int tok_init(Tokenizer *t, const uint8_t *s) {
    if (memcmp(s, "ETK1", 4) != 0) return -1;
    uint32_t v[5];
    memcpy(v, s + 4, sizeof(v));
    t->base = s;
    t->vocab = (int)v[0]; t->max_len = (int)v[1]; t->byte_base = (int)v[2];
    t->n_sorted = (int)v[3]; t->n_special = (int)v[4];
    const uint8_t *p = s + 24;
    t->special = (const int32_t *)p; p += 4 * t->n_special;
    t->scores = (const float *)p; p += 4 * t->vocab;
    t->offs = (const uint32_t *)p; p += 4 * (t->vocab + 1);
    t->sorted = (const uint16_t *)p;
    return 0;
}

static int is_special(const Tokenizer *t, int id) {
    for (int i = 0; i < t->n_special; i++) if (t->special[i] == id) return 1;
    return 0;
}

const char *tok_piece(const Tokenizer *t, int id, int *len) {
    if (id < 0 || id >= t->vocab || is_special(t, id)) { *len = 0; return ""; }
    *len = (int)(t->offs[id + 1] - t->offs[id]);
    return (const char *)(t->base + t->offs[id]);
}

static int cmp_piece(const Tokenizer *t, int id, const char *s, int n) {
    int len = (int)(t->offs[id + 1] - t->offs[id]);
    int m = len < n ? len : n;
    int c = memcmp(t->base + t->offs[id], s, (size_t)m);
    if (c) return c;
    return len - n;
}

// Look up a normal (non-special, non-byte) piece. Returns id or -1.
static int lookup(const Tokenizer *t, const char *s, int n) {
    int lo = 0, hi = t->n_sorted - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2, id = t->sorted[mid];
        int c = cmp_piece(t, id, s, n);
        if (c == 0) return id;
        if (c < 0) lo = mid + 1; else hi = mid - 1;
    }
    return -1;
}

int tok_encode(const Tokenizer *t, const char *text, int *out, int max_out) {
    int n = 0;
    char ch = ' ';  // SentencePiece dummy prefix
    const char *p = text;
    for (;;) {
        if (n >= max_out) break;
        int id = lookup(t, &ch, 1);
        out[n++] = id >= 0 ? id : t->byte_base + (uint8_t)ch;
        if (!*p) break;
        ch = *p++;
    }
    char buf[128];
    for (;;) {  // repeatedly merge the adjacent pair whose merged piece scores highest
        float best = -1e30f;
        int best_i = -1, best_id = -1;
        for (int i = 0; i + 1 < n; i++) {
            int la, lb;
            const char *a = tok_piece(t, out[i], &la), *b = tok_piece(t, out[i + 1], &lb);
            if (la + lb > (int)sizeof(buf) || la == 0 || lb == 0) continue;
            memcpy(buf, a, (size_t)la);
            memcpy(buf + la, b, (size_t)lb);
            int id = lookup(t, buf, la + lb);
            if (id >= 0 && t->scores[id] > best) { best = t->scores[id]; best_i = i; best_id = id; }
        }
        if (best_i < 0) break;
        out[best_i] = best_id;
        memmove(out + best_i + 1, out + best_i + 2, sizeof(int) * (size_t)(n - best_i - 2));
        n--;
    }
    return n;
}
