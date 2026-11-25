// BM25 knowledge-base search over kb.bin on the SD card (or any file).
// Mirror of BM25Index / words() in pipeline/lib/kbtext.py.
#pragma once
#include <stdint.h>
#include <stdio.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    FILE *f;
    uint32_t n_passages, n_buckets, n_terms, off_buckets, off_terms, off_pidx, off_text;
    float min_score;
    char *stop_blob;  // stopwords, NUL-separated, sorted
    const char **stops;
    int n_stops;
} KB;

int kb_open(KB *kb, const char *path);  // 0 on success
int kb_open_fp(KB *kb, FILE *f);        // same, from an open stream (e.g. fmemopen of a flash partition); kb_close closes it
void kb_close(KB *kb);
// Best passage id for a query (or -1); *score gets its BM25 score.
int kb_search(KB *kb, const char *query, float *score);
// Copy passage text into buf (NUL-terminated). Returns length, or -1.
int kb_passage(KB *kb, int id, char *buf, int bufsize);

#ifdef __cplusplus
}
#endif
