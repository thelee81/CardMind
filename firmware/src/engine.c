#include "engine.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

static uint32_t rd32(const uint8_t *p) { uint32_t v; memcpy(&v, p, 4); return v; }
static int32_t rdi(const uint8_t *p) { int32_t v; memcpy(&v, p, 4); return v; }
static float rdf(const uint8_t *p) { float v; memcpy(&v, p, 4); return v; }

int model_parse_header(const void *data, size_t size, ModelHeader *h) {
    const uint8_t *b = (const uint8_t *)data;
    if (size < 256 || memcmp(b, "ELM1", 4) != 0 || rd32(b + 4) != 1) return -1;
    h->dim = rdi(b + 8); h->hidden = rdi(b + 12); h->n_layers = rdi(b + 16);
    h->n_heads = rdi(b + 20); h->n_kv_heads = rdi(b + 24); h->vocab = rdi(b + 28);
    h->max_seq = rdi(b + 32); h->rope_theta = rdf(b + 36); h->group = rdi(b + 40);
    h->weights_offset = rd32(b + 44); h->tokenizer_offset = rd32(b + 48);
    h->total_size = rd32(b + 52); h->crc = rd32(b + 56);
    h->bos = rdi(b + 60); h->eos = rdi(b + 64); h->ctx = rdi(b + 68);
    h->usr = rdi(b + 72); h->bot = rdi(b + 76); h->eot = rdi(b + 80);
    if (h->dim <= 0 || h->n_heads <= 0 || h->dim % h->n_heads || h->n_kv_heads <= 0 ||
        h->n_heads % h->n_kv_heads || h->group <= 0 || h->dim % h->group || h->hidden % h->group)
        return -2;
    return 0;
}

size_t engine_kv_bytes_per_pos(const ModelHeader *h) {
    size_t kv_dim = (size_t)(h->dim / h->n_heads) * h->n_kv_heads;
    return (size_t)h->n_layers * (2 * kv_dim + 2 * sizeof(float) * h->n_kv_heads);
}

size_t engine_work_bytes(const ModelHeader *h, int ctx_len) {
    size_t B = ENGINE_BATCH, mx = h->dim > h->hidden ? h->dim : h->hidden;
    size_t kv_dim = (size_t)(h->dim / h->n_heads) * h->n_kv_heads;
    size_t fl = B * (5 * h->dim + 2 * h->hidden + 2 * kv_dim) + ctx_len + h->vocab + B * mx / h->group;
    return fl * sizeof(float) + B * mx + (size_t)h->n_layers * 7 * sizeof(QMat) + 4 * h->n_layers * sizeof(void *);
}

static const uint8_t *take_qmat(QMat *m, const uint8_t *p, int rows, int cols) {
    size_t n = 4 * (size_t)rows + (size_t)rows * cols;
    m->scale = (const float *)p;
    m->q = (const int8_t *)(p + 4 * (size_t)rows);
    m->rows = rows;
    m->cols = cols;
    return p + n + ((4 - n % 4) % 4);
}

void engine_free(Engine *e) {
    if (e->kq) for (int l = 0; l < e->h.n_layers; l++) { free(e->kq[l]); free(e->vq[l]); free(e->ks[l]); free(e->vs[l]); }
    free(e->kq); free(e->vq); free(e->ks); free(e->vs); free(e->w);
    free(e->x); free(e->xb); free(e->xb2); free(e->hb); free(e->hb2);
    free(e->q); free(e->k); free(e->v); free(e->att); free(e->logits); free(e->aq); free(e->as);
    memset(e, 0, sizeof(*e));
}

int engine_init(Engine *e, const void *data, size_t size, int ctx_len) {
    memset(e, 0, sizeof(*e));
    if (model_parse_header(data, size, &e->h) != 0) return -1;
    ModelHeader *h = &e->h;
    if (h->total_size > size) return -2;
    e->base = (const uint8_t *)data;
    e->head_dim = h->dim / h->n_heads;
    e->kv_dim = e->head_dim * h->n_kv_heads;
    e->ctx_len = (ctx_len <= 0 || ctx_len > h->max_seq) ? h->max_seq : ctx_len;

    const uint8_t *p = e->base + h->weights_offset;
    e->rms_att = (const float *)p; p += 4 * (size_t)h->n_layers * h->dim;
    e->rms_ffn = (const float *)p; p += 4 * (size_t)h->n_layers * h->dim;
    e->rms_final = (const float *)p; p += 4 * (size_t)h->dim;
    p = take_qmat(&e->emb, p, h->vocab, h->dim);
    e->w = (QMat *)calloc((size_t)h->n_layers * 7, sizeof(QMat));
    if (!e->w) return -3;
    for (int l = 0; l < h->n_layers; l++) {
        QMat *m = e->w + 7 * l;
        p = take_qmat(&m[0], p, h->dim, h->dim);        // wq
        p = take_qmat(&m[1], p, e->kv_dim, h->dim);     // wk
        p = take_qmat(&m[2], p, e->kv_dim, h->dim);     // wv
        p = take_qmat(&m[3], p, h->dim, h->dim);        // wo
        p = take_qmat(&m[4], p, h->hidden, h->dim);     // w1
        p = take_qmat(&m[5], p, h->dim, h->hidden);     // w2
        p = take_qmat(&m[6], p, h->hidden, h->dim);     // w3
    }
    if ((size_t)(p - e->base) > h->tokenizer_offset) return -4;

    int B = ENGINE_BATCH, mx = h->dim > h->hidden ? h->dim : h->hidden;
#define ALLOC(ptr, n) do { (ptr) = calloc((size_t)(n), sizeof(*(ptr))); if (!(ptr)) { engine_free(e); return -5; } } while (0)
    ALLOC(e->x, B * h->dim); ALLOC(e->xb, B * h->dim); ALLOC(e->xb2, B * h->dim);
    ALLOC(e->hb, B * h->hidden); ALLOC(e->hb2, B * h->hidden);
    ALLOC(e->q, B * h->dim); ALLOC(e->k, B * e->kv_dim); ALLOC(e->v, B * e->kv_dim);
    ALLOC(e->att, e->ctx_len); ALLOC(e->logits, h->vocab);
    ALLOC(e->aq, B * mx); ALLOC(e->as, B * mx / h->group);
    ALLOC(e->kq, h->n_layers); ALLOC(e->vq, h->n_layers); ALLOC(e->ks, h->n_layers); ALLOC(e->vs, h->n_layers);
    for (int l = 0; l < h->n_layers; l++) {  // one block per layer: avoids needing one huge free block
        ALLOC(e->kq[l], e->ctx_len * e->kv_dim); ALLOC(e->vq[l], e->ctx_len * e->kv_dim);
        ALLOC(e->ks[l], e->ctx_len * h->n_kv_heads); ALLOC(e->vs[l], e->ctx_len * h->n_kv_heads);
    }
#undef ALLOC
    return 0;
}

// ---------------------------------------------------------------- kernels
static void rmsnorm(float *o, const float *x, const float *w, int n) {
    float ss = 0.0f;
    for (int i = 0; i < n; i++) ss += x[i] * x[i];
    ss = 1.0f / sqrtf(ss / n + 1e-5f);
    for (int i = 0; i < n; i++) o[i] = x[i] * ss * w[i];
}

static void quant_vec(int8_t *q, float *s, const float *x, int n, int G) {
    for (int g = 0; g < n / G; g++) {
        const float *xg = x + g * G;
        float amax = 0.0f;
        for (int j = 0; j < G; j++) { float a = fabsf(xg[j]); if (a > amax) amax = a; }
        float sc = amax / 127.0f;
        if (sc == 0.0f) sc = 1.0f;
        s[g] = sc;
        for (int j = 0; j < G; j++) {
            float r = roundf(xg[j] / sc);
            q[g * G + j] = (int8_t)(r > 127.0f ? 127 : (r < -127.0f ? -127 : r));
        }
    }
}

// out[b][i] = scale[i] * sum_g as[b][g] * sum_{j in g} W[i][j] * aq[b][j]
static void matmul(Engine *e, float *out, const QMat *m, const float *x, int n) {
    const int G = e->h.group, cols = m->cols, ng = cols / G;
    for (int b = 0; b < n; b++) quant_vec(e->aq + b * cols, e->as + b * ng, x + b * cols, cols, G);
    for (int i = 0; i < m->rows; i++) {
        const int8_t *wr = m->q + (size_t)i * cols;  // read each weight row from flash once per batch
        for (int b = 0; b < n; b++) {
            const int8_t *xq = e->aq + b * cols;
            const float *xs = e->as + b * ng;
            float acc = 0.0f;
            for (int g = 0; g < ng; g++) {
                int32_t s = 0;
                const int8_t *wg = wr + g * G, *xg = xq + g * G;
                for (int j = 0; j < G; j++) s += (int32_t)wg[j] * xg[j];
                acc += (float)s * xs[g];
            }
            out[b * m->rows + i] = acc * m->scale[i];
        }
    }
}

static void rope(float *v, int n_heads, int hd, int pos, float theta) {
    for (int i = 0; i < hd / 2; i++) {
        float ang = (float)pos * powf(theta, -2.0f * (float)i / (float)hd);
        float c = cosf(ang), s = sinf(ang);
        for (int h = 0; h < n_heads; h++) {
            float *p = v + h * hd + 2 * i;
            float x0 = p[0], x1 = p[1];
            p[0] = x0 * c - x1 * s;
            p[1] = x0 * s + x1 * c;
        }
    }
}

static void store_kv(int8_t *q, float *s, const float *x, int n_kv_heads, int hd) {
    for (int h = 0; h < n_kv_heads; h++) {
        const float *xh = x + h * hd;
        float amax = 0.0f;
        for (int j = 0; j < hd; j++) { float a = fabsf(xh[j]); if (a > amax) amax = a; }
        float sc = amax / 127.0f;
        if (sc == 0.0f) sc = 1.0f;
        s[h] = sc;
        for (int j = 0; j < hd; j++) {
            float r = roundf(xh[j] / sc);
            q[h * hd + j] = (int8_t)(r > 127.0f ? 127 : (r < -127.0f ? -127 : r));
        }
    }
}

const float *engine_forward(Engine *e, const int *tokens, int n, int pos) {
    const ModelHeader *h = &e->h;
    const int D = h->dim, HD = e->head_dim, KVD = e->kv_dim, HID = h->hidden;
    const int rep = h->n_heads / h->n_kv_heads;
    const float inv_sqrt = 1.0f / sqrtf((float)HD);
    if (n < 1) return e->logits;
    if (n > ENGINE_BATCH) n = ENGINE_BATCH;

    for (int b = 0; b < n; b++) {
        const int8_t *r = e->emb.q + (size_t)tokens[b] * D;
        float sc = e->emb.scale[tokens[b]];
        for (int i = 0; i < D; i++) e->x[b * D + i] = r[i] * sc;
    }
    for (int l = 0; l < h->n_layers; l++) {
        const QMat *m = e->w + 7 * l;
        for (int b = 0; b < n; b++) rmsnorm(e->xb + b * D, e->x + b * D, e->rms_att + l * D, D);
        matmul(e, e->q, &m[0], e->xb, n);
        matmul(e, e->k, &m[1], e->xb, n);
        matmul(e, e->v, &m[2], e->xb, n);
        for (int b = 0; b < n; b++) {
            int p = pos + b;
            rope(e->q + b * D, h->n_heads, HD, p, h->rope_theta);
            rope(e->k + b * KVD, h->n_kv_heads, HD, p, h->rope_theta);
            store_kv(e->kq[l] + (size_t)p * KVD, e->ks[l] + (size_t)p * h->n_kv_heads, e->k + b * KVD, h->n_kv_heads, HD);
            store_kv(e->vq[l] + (size_t)p * KVD, e->vs[l] + (size_t)p * h->n_kv_heads, e->v + b * KVD, h->n_kv_heads, HD);
        }
        for (int b = 0; b < n; b++) {
            int p = pos + b;
            for (int hh = 0; hh < h->n_heads; hh++) {
                int kh = hh / rep;
                const float *qh = e->q + b * D + hh * HD;
                float mx = -1e30f;
                for (int t = 0; t <= p; t++) {
                    const int8_t *kt = e->kq[l] + (size_t)t * KVD + kh * HD;
                    float s = 0.0f;
                    for (int j = 0; j < HD; j++) s += qh[j] * kt[j];
                    s *= e->ks[l][t * h->n_kv_heads + kh] * inv_sqrt;
                    e->att[t] = s;
                    if (s > mx) mx = s;
                }
                float sum = 0.0f;
                for (int t = 0; t <= p; t++) { e->att[t] = expf(e->att[t] - mx); sum += e->att[t]; }
                float *o = e->xb2 + b * D + hh * HD;
                for (int j = 0; j < HD; j++) o[j] = 0.0f;
                for (int t = 0; t <= p; t++) {
                    float a = e->att[t] / sum * e->vs[l][t * h->n_kv_heads + kh];
                    const int8_t *vt = e->vq[l] + (size_t)t * KVD + kh * HD;
                    for (int j = 0; j < HD; j++) o[j] += a * vt[j];
                }
            }
        }
        matmul(e, e->xb, &m[3], e->xb2, n);
        for (int i = 0; i < n * D; i++) e->x[i] += e->xb[i];
        for (int b = 0; b < n; b++) rmsnorm(e->xb + b * D, e->x + b * D, e->rms_ffn + l * D, D);
        matmul(e, e->hb, &m[4], e->xb, n);
        matmul(e, e->hb2, &m[6], e->xb, n);
        for (int i = 0; i < n * HID; i++) {
            float a = e->hb[i];
            e->hb[i] = a / (1.0f + expf(-a)) * e->hb2[i];
        }
        matmul(e, e->xb, &m[5], e->hb, n);
        for (int i = 0; i < n * D; i++) e->x[i] += e->xb[i];
    }
    rmsnorm(e->xb, e->x + (n - 1) * D, e->rms_final, D);
    matmul(e, e->logits, &e->emb, e->xb, 1);
    return e->logits;
}
