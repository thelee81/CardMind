// kb.bin layout (little-endian), written by BM25Index.write_bin():
//   header 64 B: "EKB1", u32 version, u32 n_passages, u32 n_buckets, u32 n_terms, f32 min_score,
//                u32 off_buckets, off_terms, off_pidx, off_text, off_stop, stop_len
//   u32 bucket_start[n_buckets+1]          index into the term table
//   term[n_terms]: u32 hash, u32 n_postings, u32 off_postings   (sorted by hash % n_buckets, hash)
//   postings: (u32 passage_id, f32 bm25_weight)
//   u32 passage_offset[n_passages+1], passage text bytes, stopwords (space separated)
#include "kb.h"

#include <stdlib.h>
#include <string.h>

#define MAX_WORD 32
#define MAX_QWORDS 48
#define CAND_SIZE 2048  // open-addressing table of candidate passages

static uint32_t rd32(const uint8_t *p) { uint32_t v; memcpy(&v, p, 4); return v; }

static int read_at(FILE *f, uint32_t off, void *buf, size_t n) {
    if (fseek(f, (long)off, SEEK_SET) != 0) return -1;
    return fread(buf, 1, n, f) == n ? 0 : -1;
}

int kb_open(KB *kb, const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) { memset(kb, 0, sizeof(*kb)); return -1; }
    return kb_open_fp(kb, f);
}

int kb_open_fp(KB *kb, FILE *f) {
    memset(kb, 0, sizeof(*kb));
    kb->f = f;
    if (!kb->f) return -1;
    uint8_t h[64];
    if (read_at(kb->f, 0, h, 64) || memcmp(h, "EKB1", 4) || rd32(h + 4) != 1) { kb_close(kb); return -2; }
    kb->n_passages = rd32(h + 8); kb->n_buckets = rd32(h + 12); kb->n_terms = rd32(h + 16);
    memcpy(&kb->min_score, h + 20, 4);
    kb->off_buckets = rd32(h + 24); kb->off_terms = rd32(h + 28);
    kb->off_pidx = rd32(h + 32); kb->off_text = rd32(h + 36);
    uint32_t off_stop = rd32(h + 40), stop_len = rd32(h + 44);
    kb->stop_blob = (char *)malloc(stop_len + 1);
    if (!kb->stop_blob || read_at(kb->f, off_stop, kb->stop_blob, stop_len)) { kb_close(kb); return -3; }
    kb->stop_blob[stop_len] = 0;
    int n = stop_len ? 1 : 0;
    for (uint32_t i = 0; i < stop_len; i++) if (kb->stop_blob[i] == ' ') n++;
    kb->stops = (const char **)malloc(sizeof(char *) * (n ? n : 1));
    if (!kb->stops) { kb_close(kb); return -3; }
    char *p = kb->stop_blob;
    for (int i = 0; i < n; i++) {
        kb->stops[i] = p;
        char *sp = strchr(p, ' ');
        if (sp) { *sp = 0; p = sp + 1; }
    }
    kb->n_stops = n;
    return 0;
}

void kb_close(KB *kb) {
    if (kb->f) fclose(kb->f);
    free(kb->stop_blob);
    free((void *)kb->stops);
    memset(kb, 0, sizeof(*kb));
}

static int is_stop(const KB *kb, const char *w) {
    int lo = 0, hi = kb->n_stops - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2, c = strcmp(kb->stops[mid], w);
        if (c == 0) return 1;
        if (c < 0) lo = mid + 1; else hi = mid - 1;
    }
    return 0;
}

static uint32_t fnv1a(const char *s) {
    uint32_t h = 0x811C9DC5u;
    for (; *s; s++) { h ^= (uint8_t)*s; h *= 0x01000193u; }
    return h;
}

// Same rules as words() in kbtext.py. Returns number of unique word hashes.
static int query_hashes(const KB *kb, const char *text, uint32_t *out, int max_out) {
    char w[MAX_WORD + 1];
    int wl = 0, raw = 0, n = 0;
    for (const char *p = text;; p++) {
        char c = *p;
        if (c >= 'A' && c <= 'Z') c = (char)(c + 32);
        if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')) {
            if (wl < MAX_WORD) w[wl++] = c;
            raw++;
            continue;
        }
        if (raw) {
            w[wl] = 0;
            int digits = 1;
            for (int i = 0; i < wl; i++) if (w[i] < '0' || w[i] > '9') digits = 0;
            int keep = !(wl < 2 && !digits) && !is_stop(kb, w);
            if (keep) {
                if (wl > 3 && w[wl - 1] == 's' && w[wl - 2] != 's') w[--wl] = 0;
                uint32_t h = fnv1a(w);
                int dup = 0;
                for (int i = 0; i < n; i++) if (out[i] == h) dup = 1;
                if (!dup && n < max_out) out[n++] = h;
            }
            wl = raw = 0;
        }
        if (!c) break;
    }
    return n;
}

typedef struct { uint32_t id; float score; } Cand;

int kb_search(KB *kb, const char *query, float *score) {
    *score = 0.0f;
    if (!kb->f || kb->n_buckets == 0) return -1;
    uint32_t qh[MAX_QWORDS];
    int nq = query_hashes(kb, query, qh, MAX_QWORDS);
    if (!nq) return -1;
    Cand *cand = (Cand *)malloc(sizeof(Cand) * CAND_SIZE);
    if (!cand) return -1;
    for (int i = 0; i < CAND_SIZE; i++) cand[i].id = 0xFFFFFFFFu;
    for (int qi = 0; qi < nq; qi++) {
        uint32_t h = qh[qi], b = h % kb->n_buckets, range[2];
        if (read_at(kb->f, kb->off_buckets + 4 * b, range, 8)) continue;
        uint32_t n_post = 0, off_post = 0;
        uint8_t te[12 * 16];
        for (uint32_t t = range[0]; t < range[1] && !off_post; t += 16) {
            uint32_t cnt = range[1] - t < 16 ? range[1] - t : 16;
            if (read_at(kb->f, kb->off_terms + 12 * t, te, 12 * cnt)) break;
            for (uint32_t k = 0; k < cnt; k++)
                if (rd32(te + 12 * k) == h) { n_post = rd32(te + 12 * k + 4); off_post = rd32(te + 12 * k + 8); break; }
        }
        uint8_t pb[8 * 64];
        for (uint32_t i = 0; i < n_post; i += 64) {
            uint32_t cnt = n_post - i < 64 ? n_post - i : 64;
            if (read_at(kb->f, off_post + 8 * i, pb, 8 * cnt)) break;
            for (uint32_t k = 0; k < cnt; k++) {
                uint32_t id = rd32(pb + 8 * k);
                float w;
                memcpy(&w, pb + 8 * k + 4, 4);
                uint32_t slot = (id * 2654435761u) % CAND_SIZE;
                for (int probe = 0; probe < CAND_SIZE; probe++) {
                    Cand *c = &cand[(slot + probe) % CAND_SIZE];
                    if (c->id == id) { c->score += w; break; }
                    if (c->id == 0xFFFFFFFFu) { c->id = id; c->score = w; break; }
                }
            }
        }
    }
    int best = -1;
    float bs = 0.0f;
    for (int i = 0; i < CAND_SIZE; i++) {
        if (cand[i].id == 0xFFFFFFFFu) continue;
        if (best < 0 || cand[i].score > bs || (cand[i].score == bs && (int)cand[i].id < best)) {
            best = (int)cand[i].id;
            bs = cand[i].score;
        }
    }
    free(cand);
    *score = bs;
    return best;
}

int kb_passage(KB *kb, int id, char *buf, int bufsize) {
    if (!kb->f || id < 0 || (uint32_t)id >= kb->n_passages || bufsize < 1) return -1;
    uint32_t r[2];
    if (read_at(kb->f, kb->off_pidx + 4 * (uint32_t)id, r, 8)) return -1;
    uint32_t n = r[1] - r[0];
    if (n > (uint32_t)bufsize - 1) n = (uint32_t)bufsize - 1;
    if (read_at(kb->f, r[0], buf, n)) return -1;
    buf[n] = 0;
    return (int)n;
}
