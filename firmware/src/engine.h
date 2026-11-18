// Tiny int8 transformer inference engine (portable C99: runs on ESP32-S3 and on a PC).
// Weights are read in place from model.bin (on the device: memory-mapped flash).
// Format: see pipeline/08_export.py. Reference implementation: pipeline/lib/npref.py.
#pragma once
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define ENGINE_BATCH 4  // tokens processed together during prompt prefill

typedef struct {
    int dim, hidden, n_layers, n_heads, n_kv_heads, vocab, max_seq, group;
    float rope_theta;
    uint32_t weights_offset, tokenizer_offset, total_size, crc;
    int bos, eos, ctx, usr, bot, eot;
} ModelHeader;

typedef struct {
    const float *scale;  // [rows]
    const int8_t *q;     // [rows * cols]
    int rows, cols;
} QMat;

typedef struct {
    ModelHeader h;
    const uint8_t *base;
    const float *rms_att, *rms_ffn, *rms_final;
    QMat emb;
    QMat *w;  // n_layers * 7: wq wk wv wo w1 w2 w3
    int head_dim, kv_dim, ctx_len;
    int8_t **kq, **vq;  // per layer [ctx_len * kv_dim]
    float **ks, **vs;   // per layer [ctx_len * n_kv_heads]
    float *x, *xb, *xb2, *hb, *hb2, *q, *k, *v, *att, *logits;
    int8_t *aq;
    float *as;
} Engine;

// Returns 0 if `data` starts with a valid model header.
int model_parse_header(const void *data, size_t size, ModelHeader *h);
// KV-cache RAM needed per context position (use it to size ctx_len to free RAM).
size_t engine_kv_bytes_per_pos(const ModelHeader *h);
// RAM needed for everything except the KV cache.
size_t engine_work_bytes(const ModelHeader *h, int ctx_len);
// ctx_len <= 0 means the model's max_seq. Returns 0 on success.
int engine_init(Engine *e, const void *data, size_t size, int ctx_len);
void engine_free(Engine *e);
// Run n (1..ENGINE_BATCH) tokens at positions pos..pos+n-1. Returns logits of the last one.
const float *engine_forward(Engine *e, const int *tokens, int n, int pos);

#ifdef __cplusplus
}
#endif
