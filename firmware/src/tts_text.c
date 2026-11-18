#include "tts_text.h"

#include <stdlib.h>
#include <string.h>

// ---------------------------------------------------------------- sentence splitter
void tts_split_init(TtsSplitter *s, tts_sentence_fn fn, void *user) {
    memset(s, 0, sizeof(*s));
    s->fn = fn;
    s->user = user;
}

static void emit_sentence(TtsSplitter *s) {
    s->buf[s->len] = 0;
    int start = 0;
    while (s->buf[start] == ' ') start++;
    if (s->buf[start]) s->fn(s->buf + start, s->user);
    s->len = 0;
    s->ended = 0;
}

void tts_split_feed(TtsSplitter *s, const char *text, int len) {
    for (int i = 0; i < len; i++) {
        char c = text[i];
        if (s->ended) {
            if (c == ' ') { emit_sentence(s); continue; }
            if (!(c == '.' || c == '!' || c == '?')) s->ended = 0;  // e.g. the 4 in 3.4
        }
        if (s->len >= TTS_SENTENCE_MAX - 1) {  // too long: break at the last space
            int cut = s->len;
            while (cut > 0 && s->buf[cut] != ' ') cut--;
            if (cut <= 0) cut = s->len;
            char rest[TTS_SENTENCE_MAX + 1];
            int nrest = s->len - cut;
            memcpy(rest, s->buf + cut, (size_t)nrest);
            s->len = cut;
            emit_sentence(s);
            memcpy(s->buf, rest, (size_t)nrest);
            s->len = nrest;
        }
        s->buf[s->len++] = c;
        if (c == '.' || c == '!' || c == '?') s->ended = 1;
    }
}

void tts_split_flush(TtsSplitter *s) {
    if (s->len) emit_sentence(s);
}

// ---------------------------------------------------------------- word tables
// Pronunciation fixes: SAM reads American English letter rules. Add your own words here
// (lowercase key; replacement in plain spelling SAM pronounces well).
static const char *DICT[][2] = {
    {"mrt", "em ar tee"}, {"hdb", "aitch dee bee"}, {"psle", "pee ess el ee"}, {"moe", "em oh ee"},
    {"cardputer", "card pewter"}, {"metre", "meeter"}, {"metres", "meeters"},
    {"centimetre", "centimeeter"}, {"centimetres", "centimeeters"}, {"kilometre", "kilomeeter"},
    {"kilometres", "kilomeeters"}, {"millimetre", "millimeeter"}, {"millimetres", "millimeeters"},
    {"litre", "leeter"}, {"litres", "leeters"}, {"millilitre", "millileeter"}, {"millilitres", "millileeters"},
    {"centre", "center"}, {"centres", "centers"}, {"favourite", "favorite"}, {"colour", "color"}, {"colours", "colors"}, {"maths", "maths"}, {"singapore", "sing a pore"},
    {"ok", "okay"}, {"vs", "versus"}, {"eg", "for example"}, {"ie", "that is"}, {"bolt", "bolt"},
    {"hawker", "hawker"}, {"sungei", "soong ay"}, {"buloh", "boo lo"}, {"bukit", "boo kit"},
    {"timah", "tee ma"}, {"newater", "new water"}, {"photosynthesis", "foto sin the sis"},
};
// Units read after a number: {abbreviation, singular, plural}
static const char *UNITS[][3] = {
    {"km", "kilomeeter", "kilomeeters"}, {"m", "meeter", "meeters"}, {"cm", "centimeeter", "centimeeters"},
    {"mm", "millimeeter", "millimeeters"}, {"kg", "kilogram", "kilograms"}, {"g", "gram", "grams"},
    {"l", "leeter", "leeters"}, {"ml", "millileeter", "millileeters"},
    {"min", "minute", "minutes"},
};
static const char *ONES[] = {"zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
                             "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
                             "seventeen", "eighteen", "nineteen"};
static const char *TENS[] = {"", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"};
static const char *ORD[] = {"", "", "half", "third", "quarter", "fifth", "sixth", "seventh", "eighth", "ninth",
                            "tenth", "eleventh", "twelfth"};

// ---------------------------------------------------------------- output buffer
typedef struct { char *p; int n, cap; } Out;

static void put(Out *o, const char *s) {  // append a word, space-separated
    if (o->n && o->p[o->n - 1] != ' ' && o->n < o->cap - 1) o->p[o->n++] = ' ';
    for (; *s && o->n < o->cap - 1; s++) o->p[o->n++] = *s;
    o->p[o->n] = 0;
}

static void punct(Out *o, char c) {  // attach punctuation to the previous word
    while (o->n && o->p[o->n - 1] == ' ') o->n--;
    if (o->n && (o->p[o->n - 1] == ',' || o->p[o->n - 1] == '.' || o->p[o->n - 1] == '?')) {
        if (c == ',') { o->p[o->n++] = ' '; o->p[o->n] = 0; return; }  // keep the stronger mark
        o->n--;
    }
    if (o->n && o->n < o->cap - 2) { o->p[o->n++] = c; o->p[o->n++] = ' '; }
    o->p[o->n] = 0;
}

static void put_int(Out *o, long long v) {
    if (v < 0) { put(o, "minus"); v = -v; }
    if (v >= 1000000000000LL) {  // too big to read nicely: digit by digit
        char d[24];
        int n = 0;
        while (v && n < 23) { d[n++] = (char)('0' + v % 10); v /= 10; }
        while (n--) put(o, ONES[d[n] - '0']);
        return;
    }
    static const long long SCALE[] = {1000000000LL, 1000000LL, 1000LL};
    static const char *SNAME[] = {"billion", "million", "thousand"};
    int said = 0;
    for (int i = 0; i < 3; i++) {
        if (v >= SCALE[i]) { put_int(o, v / SCALE[i]); put(o, SNAME[i]); v %= SCALE[i]; said = 1; }
    }
    if (v >= 100) { put(o, ONES[v / 100]); put(o, "hundred"); v %= 100; said = 1; if (v) put(o, "and"); }
    else if (said && v) put(o, "and");
    if (v >= 20) {
        put(o, TENS[v / 10]);
        if (v % 10) put(o, ONES[v % 10]);
    } else if (v || !said) {
        put(o, ONES[v]);
    }
}

// ---------------------------------------------------------------- tokens
enum { K_NUM, K_WORD, K_SYM };
typedef struct {
    int kind, space_before;
    char text[40];   // number digits (no commas) or word
    char sym;
    int is_int;
} Tk;
#define MAX_TK 128

static char lowc(char c) { return (c >= 'A' && c <= 'Z') ? (char)(c + 32) : c; }
static int isdig(char c) { return c >= '0' && c <= '9'; }
static int isalpha_(char c) { c = lowc(c); return c >= 'a' && c <= 'z'; }

static int lex(const char *s, Tk *t) {
    int n = 0, sp = 1;
    while (*s && n < MAX_TK) {
        char c = *s;
        if (c == ' ') { sp = 1; s++; continue; }
        Tk *k = &t[n];
        memset(k, 0, sizeof(*k));
        k->space_before = sp;
        sp = 0;
        if (isdig(c)) {
            int m = 0;
            k->kind = K_NUM;
            k->is_int = 1;
            while (*s && m < 38) {
                if (isdig(*s)) k->text[m++] = *s++;
                else if (*s == ',' && isdig(s[1]) && isdig(s[2]) && isdig(s[3]) && !isdig(s[4])) s++;
                else if (*s == '.' && isdig(s[1]) && k->is_int) { k->is_int = 0; k->text[m++] = *s++; }
                else break;
            }
            // a letter glued to the number: "12x7" or "5cm" -> separate tokens
        } else if (isalpha_(c)) {
            int m = 0;
            k->kind = K_WORD;
            while (*s && (isalpha_(*s) || (*s == '\'' && isalpha_(s[1])))) {
                if (m < 38) k->text[m++] = lowc(*s);
                s++;
            }
        } else {
            k->kind = K_SYM;
            k->sym = c;
            s++;
        }
        n++;
    }
    return n;
}

static const char *dict_lookup(const char *w) {
    for (size_t i = 0; i < sizeof(DICT) / sizeof(DICT[0]); i++) if (!strcmp(DICT[i][0], w)) return DICT[i][1];
    return NULL;
}

static int unit_index(const char *w) {
    for (size_t i = 0; i < sizeof(UNITS) / sizeof(UNITS[0]); i++) if (!strcmp(UNITS[i][0], w)) return (int)i;
    return -1;
}

static void put_number(Out *o, const Tk *k) {
    if (k->is_int) { put_int(o, atoll(k->text)); return; }
    const char *dot = strchr(k->text, '.');
    put_int(o, atoll(k->text));
    put(o, "point");
    for (const char *p = dot + 1; *p; p++) put(o, ONES[*p - '0']);
}

int tts_normalize(const char *in, char *out, int outsize) {
    Tk t[MAX_TK];
    int n = lex(in, t);
    Out o = {out, 0, outsize};
    out[0] = 0;
    for (int i = 0; i < n; i++) {
        Tk *k = &t[i];
        Tk *nx = i + 1 < n ? &t[i + 1] : NULL, *nx2 = i + 2 < n ? &t[i + 2] : NULL;
        int prev_num = i > 0 && t[i - 1].kind == K_NUM;
        if (k->kind == K_NUM) {
            // mixed number 2 3/4 -> "two and three quarters" (the fraction is spoken on the next token)
            Tk *nx3 = i + 3 < n ? &t[i + 3] : NULL;
            if (nx && nx2 && nx3 && k->is_int && nx->kind == K_NUM && nx->is_int && nx->space_before &&
                nx2->kind == K_SYM && nx2->sym == '/' && !nx2->space_before && nx3->kind == K_NUM &&
                nx3->is_int && !nx3->space_before && atoll(nx->text) < atoll(nx3->text)) {
                put_int(&o, atoll(k->text));
                put(&o, "and");
                continue;
            }
            // fraction 3/4 (no spaces)
            if (nx && nx2 && nx->kind == K_SYM && nx->sym == '/' && !nx->space_before && nx2->kind == K_NUM &&
                !nx2->space_before && k->is_int && nx2->is_int) {
                long long a = atoll(k->text), b = atoll(nx2->text);
                const char *ord = b >= 2 && b <= 12 ? ORD[b] : (b == 100 ? "hundredth" : (b == 1000 ? "thousandth" : NULL));
                put_int(&o, a);
                if (ord) {
                    char w[24];
                    if (a == 1) strcpy(w, ord);
                    else if (b == 2) strcpy(w, "halves");
                    else { strcpy(w, ord); strcat(w, "s"); }
                    put(&o, w);
                } else {
                    put(&o, "over");
                    put_int(&o, b);
                }
                i += 2;
                continue;
            }
            put_number(&o, k);
            if (nx && nx->kind == K_WORD) {  // unit after a number
                int u = unit_index(nx->text);
                if (u >= 0) {
                    // "15 cm2" -> square centimetres
                    if (nx2 && nx2->kind == K_NUM && !nx2->space_before && !strcmp(nx2->text, "2")) { put(&o, "square"); i++; }
                    put(&o, (k->is_int && atoll(k->text) == 1) ? UNITS[u][1] : UNITS[u][2]);
                    i++;
                }
            }
            continue;
        }
        if (k->kind == K_WORD) {
            if (!strcmp(k->text, "x") && prev_num && nx && nx->kind == K_NUM) { put(&o, "times"); continue; }
            const char *r = dict_lookup(k->text);
            put(&o, r ? r : k->text);
            continue;
        }
        switch (k->sym) {  // symbols
            case '$':
                if (nx && nx->kind == K_NUM) {
                    long long d = atoll(nx->text);
                    put_int(&o, d);
                    put(&o, d == 1 ? "dollar" : "dollars");
                    const char *dot = strchr(nx->text, '.');
                    if (dot) {
                        int cents = 0, m = 0;
                        for (const char *p = dot + 1; *p && m < 2; p++, m++) cents = cents * 10 + (*p - '0');
                        if (m == 1) cents *= 10;
                        if (cents) { put(&o, "and"); put_int(&o, cents); put(&o, cents == 1 ? "cent" : "cents"); }
                    }
                    i++;
                } else put(&o, "dollars");
                break;
            case '+': put(&o, "plus"); break;
            case '=': put(&o, "equals"); break;
            case '*': put(&o, "times"); break;
            case '%': put(&o, "percent"); break;
            case '<': put(&o, "is less than"); break;
            case '>': put(&o, "is more than"); break;
            case '/': put(&o, prev_num && nx && nx->kind == K_NUM ? "divided by" : "or"); break;
            case '-':
                if (nx && nx->kind == K_NUM && (prev_num || (k->space_before && !nx->space_before))) put(&o, "minus");
                break;  // otherwise a hyphen: just a word break
            case '^':
                if (nx && nx->kind == K_NUM && (!strcmp(nx->text, "2") || !strcmp(nx->text, "3"))) {
                    put(&o, nx->text[0] == '2' ? "squared" : "cubed");
                    i++;
                }
                break;
            case '.': case '!': case '?': punct(&o, k->sym == '?' ? '?' : '.'); break;
            case ',': case ';': case ':': case '(': case ')': punct(&o, ','); break;
            default: break;  // quotes and other symbols are skipped
        }
    }
    while (o.n && o.p[o.n - 1] == ' ') o.p[--o.n] = 0;
    for (int i = 0; i < o.n; i++) if (o.p[i] >= 'a' && o.p[i] <= 'z') o.p[i] = (char)(o.p[i] - 32);  // SAM wants capitals
    return o.n;
}
