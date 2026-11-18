// Text preparation for the SAM speech synthesiser (portable C; tested on the PC via host_chat --say).
//  * splits the streamed reply into sentences so speech starts before the reply is finished
//  * rewrites maths and numbers into words SAM can say: "3/4 of 20 = 15" ->
//    "THREE QUARTERS OF TWENTY EQUALS FIFTEEN"
#pragma once

#ifdef __cplusplus
extern "C" {
#endif

#define TTS_SENTENCE_MAX 200

typedef void (*tts_sentence_fn)(const char *sentence, void *user);

typedef struct {
    char buf[TTS_SENTENCE_MAX + 1];
    int len;
    int ended;  // saw . ! ? and waiting to see whether a space follows (3.4 is not a sentence end)
    tts_sentence_fn fn;
    void *user;
} TtsSplitter;

void tts_split_init(TtsSplitter *s, tts_sentence_fn fn, void *user);
void tts_split_feed(TtsSplitter *s, const char *text, int len);
void tts_split_flush(TtsSplitter *s);

// Rewrite one sentence for SAM (uppercase words + simple punctuation). Returns output length.
int tts_normalize(const char *in, char *out, int outsize);

#ifdef __cplusplus
}
#endif
