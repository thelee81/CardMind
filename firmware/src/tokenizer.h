// SentencePiece-compatible BPE encoder/decoder reading the tokenizer section of model.bin.
// Zero heap: all tables are read in place (memory-mapped flash on the device).
#pragma once
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    const uint8_t *base;
    int vocab, max_len, byte_base, n_sorted, n_special;
    const int32_t *special;
    const float *scores;
    const uint32_t *offs;
    const uint16_t *sorted;
} Tokenizer;

int tok_init(Tokenizer *t, const uint8_t *section);
// Encodes text (with SentencePiece's leading space). Returns the number of ids written.
int tok_encode(const Tokenizer *t, const char *text, int *out, int max_out);
// Bytes of a piece; returns 0-length for special tokens.
const char *tok_piece(const Tokenizer *t, int id, int *len);

#ifdef __cplusplus
}
#endif
