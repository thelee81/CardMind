// Card scripts. Mirror of pipeline/lib/scripttext.py (keep identical; verify.py checks them).
#include "script.h"

#include <stdio.h>
#include <string.h>

#define MAX_DEPTH 4
#define MAX_STEPS 2000L
#define MAX_MS 600000L
#define MIC_MS 600L
#define MAX_TOK 128

const char *const SCRIPT_READINGS[SR_N] = {"battery", "temp", "mic", "ram", "uptime", "bright", "vol"};
const char *const SCRIPT_COLORS[11] = {"off", "red", "green", "blue", "white", "yellow",
                                       "orange", "purple", "pink", "cyan", "magenta"};
static const char *const OPS[6] = {"<", ">", "<=", ">=", "==", "!="};

enum { T_WORD, T_NUM, T_SYM, T_END };
typedef struct { int kind; long num; char text[16]; } Tok;

typedef struct {
    Tok t[MAX_TOK];
    int n, i, nodes;
    Script *s;
    char err[64];
} P;

static int lex(const char *src, P *p) {
    int n = (int)strlen(src);
    p->n = 0;
    for (int i = 0; i < n;) {
        char c = src[i];
        if (c >= 'A' && c <= 'Z') c = (char)(c + 32);
        if (p->n >= MAX_TOK - 1) return -1;
        Tok *t = &p->t[p->n];
        if (c == ' ') { i++; continue; }
        if (c >= 'a' && c <= 'z') {
            int j = i, k = 0;
            while (j < n) {
                char d = src[j];
                if (d >= 'A' && d <= 'Z') d = (char)(d + 32);
                if (!(d >= 'a' && d <= 'z')) break;
                if (k < 15) t->text[k++] = d;
                else t->text[0] = '#';  // longer than any keyword
                j++;
            }
            t->text[k] = 0;
            t->kind = T_WORD;
            p->n++;
            i = j;
        } else if (c == '-' && i + 1 < n && src[i + 1] >= '0' && src[i + 1] <= '9') {
            int j = i + 1;
            long v = 0;
            while (j < n && src[j] >= '0' && src[j] <= '9') {
                if (j - i - 1 < 9) v = v * 10 + (src[j] - '0');
                j++;
            }
            if (j - i - 1 > 9) return -1;
            t->kind = T_NUM;
            t->num = -v;
            p->n++;
            i = j;
        } else if (c >= '0' && c <= '9') {
            int j = i;
            long v = 0;
            char x = i + 1 < n ? src[i + 1] : 0;
            if (c == '0' && (x == 'x' || x == 'X')) {
                j = i + 2;
                for (;;) {
                    char d = j < n ? src[j] : 0;
                    if (d >= 'A' && d <= 'F') d = (char)(d + 32);
                    int h = d >= '0' && d <= '9' ? d - '0' : d >= 'a' && d <= 'f' ? d - 'a' + 10 : -1;
                    if (h < 0) break;
                    if (j - i < 10) v = v * 16 + h;
                    j++;
                }
                if (j == i + 2 || j - i > 10) return -1;
            } else {
                while (j < n && src[j] >= '0' && src[j] <= '9') {
                    if (j - i < 9) v = v * 10 + (src[j] - '0');
                    j++;
                }
                if (j - i > 9) return -1;
            }
            t->kind = T_NUM;
            t->num = v;
            p->n++;
            i = j;
        } else if (c == '{' || c == '}' || c == ';') {
            t->kind = T_SYM; t->text[0] = c; t->text[1] = 0; p->n++; i++;
        } else if (c == '<' || c == '>' || c == '=' || c == '!') {
            if (i + 1 < n && src[i + 1] == '=') {
                t->kind = T_SYM; t->text[0] = c; t->text[1] = '='; t->text[2] = 0; p->n++; i += 2;
            } else if (c == '<' || c == '>') {
                t->kind = T_SYM; t->text[0] = c; t->text[1] = 0; p->n++; i++;
            } else {
                return -1;
            }
        } else {
            return -1;
        }
    }
    p->t[p->n].kind = T_END;
    return 0;
}

static const Tok *peek(P *p) { return &p->t[p->i < p->n ? p->i : p->n]; }
static const Tok *take(P *p) { const Tok *t = peek(p); if (p->i < p->n) p->i++; else p->i = p->n + 1; return t; }
static int is_sym(const Tok *t, const char *s) { return t->kind == T_SYM && !strcmp(t->text, s); }
static int index_of(const char *w, const char *const *list, int n) {
    for (int i = 0; i < n; i++) if (!strcmp(w, list[i])) return i;
    return -1;
}

static int fail(P *p, const char *msg) { snprintf(p->err, sizeof(p->err), "%s", msg); return -1; }

static int num(P *p, long lo, long hi, const char *what, long *out) {
    const Tok *t = take(p);
    if (t->kind != T_NUM) { snprintf(p->err, sizeof(p->err), "%s: number expected", what); return -1; }
    if (t->num < lo || t->num > hi) { snprintf(p->err, sizeof(p->err), "%s: %ld to %ld", what, lo, hi); return -1; }
    *out = t->num;
    return 0;
}

static int sym(P *p, const char *s) {
    if (!is_sym(take(p), s)) { snprintf(p->err, sizeof(p->err), "'%s' expected", s); return -1; }
    return 0;
}

static int stmts(P *p, int depth, const char *end, short *first);

static int block(P *p, int depth, short *first) {
    if (sym(p, "{")) return -1;
    if (stmts(p, depth + 1, "}", first)) return -1;
    return sym(p, "}");
}

static int stmt(P *p, int depth, short *idx) {
    if (++p->nodes > SCRIPT_MAX_NODES) return fail(p, "script too long");
    const Tok *t = take(p);
    if (t->kind != T_WORD) return fail(p, "command expected");
    SNode *s = &p->s->n[p->s->count];
    *idx = (short)p->s->count++;
    memset(s, 0, sizeof(*s));
    s->body = s->other = s->next = -1;
    const char *w = t->text;
    long v;
    if (!strcmp(w, "led")) {
        const Tok *c = take(p);
        int k = c->kind == T_WORD ? index_of(c->text, SCRIPT_COLORS, 11) : -1;
        if (k < 0) return fail(p, "led: colour expected");
        s->kind = SK_LED; s->a = k;
    } else if (!strcmp(w, "bright")) {
        if (num(p, 10, 100, "bright", &v)) return -1;
        s->kind = SK_BRIGHT; s->a = v;
    } else if (!strcmp(w, "vol")) {
        if (num(p, 0, 100, "vol", &v)) return -1;
        s->kind = SK_VOL; s->a = v;
    } else if (!strcmp(w, "beep")) {
        s->kind = SK_BEEP; s->a = 2000; s->b = 200;
        if (peek(p)->kind == T_NUM) {
            if (num(p, 100, 8000, "beep", &s->a)) return -1;
            if (peek(p)->kind == T_NUM && num(p, 10, 2000, "beep", &s->b)) return -1;
        }
    } else if (!strcmp(w, "ir")) {
        s->kind = SK_IR;
        if (num(p, 0, 255, "ir", &s->a) || num(p, 0, 255, "ir", &s->b)) return -1;
    } else if (!strcmp(w, "wait")) {
        s->kind = SK_WAIT;
        if (num(p, 1, 60000, "wait", &s->a)) return -1;
    } else if (!strcmp(w, "show")) {
        const Tok *r = take(p);
        int k = r->kind == T_WORD ? index_of(r->text, SCRIPT_READINGS, SR_N) : -1;
        if (k < 0) return fail(p, "show: reading expected");
        s->kind = SK_SHOW; s->a = k;
    } else if (!strcmp(w, "repeat")) {
        s->kind = SK_REPEAT;
        if (num(p, 1, 100, "repeat", &s->a)) return -1;
        short b;
        if (block(p, depth, &b)) return -1;
        p->s->n[*idx].body = b;
    } else if (!strcmp(w, "if")) {
        const Tok *r = take(p);
        int k = r->kind == T_WORD ? index_of(r->text, SCRIPT_READINGS, SR_N) : -1;
        if (k < 0) return fail(p, "if: reading expected");
        const Tok *o = take(p);
        int op = o->kind == T_SYM ? index_of(o->text, OPS, 6) : -1;
        if (op < 0) return fail(p, "if: < > <= >= == != expected");
        s->kind = SK_IF; s->a = k; s->b = op;
        if (num(p, -1000000, 1000000, "if", &v)) return -1;
        p->s->n[*idx].c = v;
        short b;
        if (block(p, depth, &b)) return -1;
        p->s->n[*idx].body = b;
        const Tok *e = peek(p);
        if (e->kind == T_WORD && !strcmp(e->text, "else")) {
            take(p);
            if (block(p, depth, &b)) return -1;
            p->s->n[*idx].other = b;
        }
    } else {
        snprintf(p->err, sizeof(p->err), "unknown command '%s'", w);
        return -1;
    }
    return 0;
}

static int stmts(P *p, int depth, const char *end, short *first) {
    if (depth > MAX_DEPTH) return fail(p, "too many nested blocks");
    short prev, cur;
    if (stmt(p, depth, &cur)) return -1;
    *first = cur;
    prev = cur;
    while (is_sym(peek(p), ";")) {
        take(p);
        if ((end[0] && is_sym(peek(p), end)) || peek(p)->kind == T_END) break;  // trailing ;
        if (stmt(p, depth, &cur)) return -1;
        p->s->n[prev].next = cur;
        prev = cur;
    }
    return 0;
}

static void cost(const Script *s, short i, long long *steps, long long *ms) {
    long long st = 0, m = 0;
    for (; i >= 0; i = s->n[i].next) {
        const SNode *n = &s->n[i];
        if (n->kind == SK_REPEAT) {
            long long a, b;
            cost(s, n->body, &a, &b);
            st += 1 + n->a * a;
            m += n->a * b;
        } else if (n->kind == SK_IF) {
            long long a, b, c = 0, d = 0;
            cost(s, n->body, &a, &b);
            if (n->other >= 0) cost(s, n->other, &c, &d);
            st += 1 + (a > c ? a : c);
            m += (b > d ? b : d) + (n->a == SR_MIC ? MIC_MS : 0);
        } else {
            st += 1;
            m += n->kind == SK_WAIT ? n->a : n->kind == SK_BEEP ? n->b : (n->kind == SK_SHOW && n->a == SR_MIC) ? MIC_MS : 0;
        }
        if (st > 1000000000LL) st = 1000000000LL;
        if (m > 1000000000000LL) m = 1000000000000LL;
    }
    *steps = st;
    *ms = m;
}

int script_parse(const char *text, Script *s, char *err, int errsize) {
    static P p;  // ~2.5 KB: keep it off the 8 KB loop-task stack
    memset(&p, 0, sizeof(p));
    p.s = s;
    s->count = 0;
    s->first = -1;
    if ((int)strlen(text) > SCRIPT_MAX_CHARS) { snprintf(err, (size_t)errsize, "script too long"); return -1; }
    if (lex(text, &p)) { snprintf(err, (size_t)errsize, "unexpected character"); return -1; }
    if (p.n == 0) { snprintf(err, (size_t)errsize, "empty script"); return -1; }
    short first;
    if (stmts(&p, 1, "", &first) == 0 && peek(&p)->kind != T_END) fail(&p, "';' expected");
    if (p.err[0]) { snprintf(err, (size_t)errsize, "%s", p.err); return -1; }
    s->first = first;
    long long steps, ms;
    cost(s, s->first, &steps, &ms);
    if (steps > MAX_STEPS) { snprintf(err, (size_t)errsize, "too many steps"); return -1; }
    if (ms > MAX_MS) { snprintf(err, (size_t)errsize, "runs too long (max 10 minutes)"); return -1; }
    return 0;
}

static int put(char *out, int size, int len, const char *fmt, const char *a, long x, long y) {
    if (len >= size) return len;
    int n = snprintf(out + len, (size_t)(size - len), fmt, a, x, y);
    return n < 0 ? len : len + n;
}

static int text_list(const Script *s, short i, char *out, int size, int len) {
    for (int k = 0; i >= 0; i = s->n[i].next, k++) {
        const SNode *n = &s->n[i];
        if (k) len = put(out, size, len, "%s", "; ", 0, 0);
        switch (n->kind) {
        case SK_LED: len = put(out, size, len, "led %s", SCRIPT_COLORS[n->a], 0, 0); break;
        case SK_BRIGHT: len = put(out, size, len, "%sbright %ld", "", n->a, 0); break;
        case SK_VOL: len = put(out, size, len, "%svol %ld", "", n->a, 0); break;
        case SK_WAIT: len = put(out, size, len, "%swait %ld", "", n->a, 0); break;
        case SK_BEEP:
            if (n->a == 2000 && n->b == 200) len = put(out, size, len, "%sbeep", "", 0, 0);
            else len = put(out, size, len, "%sbeep %ld %ld", "", n->a, n->b);
            break;
        case SK_IR: len = put(out, size, len, "%sir %ld %ld", "", n->a, n->b); break;
        case SK_SHOW: len = put(out, size, len, "show %s", SCRIPT_READINGS[n->a], 0, 0); break;
        case SK_REPEAT:
            len = put(out, size, len, "%srepeat %ld { ", "", n->a, 0);
            len = text_list(s, n->body, out, size, len);
            len = put(out, size, len, "%s", " }", 0, 0);
            break;
        case SK_IF:
            len = put(out, size, len, "if %s ", SCRIPT_READINGS[n->a], 0, 0);
            len = put(out, size, len, "%s %ld { ", OPS[n->b], n->c, 0);
            len = text_list(s, n->body, out, size, len);
            len = put(out, size, len, "%s", " }", 0, 0);
            if (n->other >= 0) {
                len = put(out, size, len, "%s", " else { ", 0, 0);
                len = text_list(s, n->other, out, size, len);
                len = put(out, size, len, "%s", " }", 0, 0);
            }
            break;
        }
    }
    return len;
}

void script_text(const Script *s, char *out, int outsize) {
    out[0] = 0;
    text_list(s, s->first, out, outsize, 0);
}

void script_describe(const SNode *n, char *out, int size) {
    switch (n->kind) {
    case SK_LED: snprintf(out, (size_t)size, "led %s", SCRIPT_COLORS[n->a]); break;
    case SK_BEEP: snprintf(out, (size_t)size, "beep %ld %ld", n->a, n->b); break;
    case SK_IR: snprintf(out, (size_t)size, "ir %ld %ld", n->a, n->b); break;
    case SK_BRIGHT: snprintf(out, (size_t)size, "bright %ld", n->a); break;
    case SK_VOL: snprintf(out, (size_t)size, "vol %ld", n->a); break;
    case SK_WAIT: snprintf(out, (size_t)size, "wait %ld", n->a); break;
    default: out[0] = 0;
    }
}

static int run_list(const Script *s, short i, const ScriptIO *io, long *budget) {
    for (; i >= 0; i = s->n[i].next) {
        const SNode *n = &s->n[i];
        if (*budget <= 0) return 0;
        (*budget)--;
        if (n->kind == SK_REPEAT) {
            for (long k = 0; k < n->a; k++)
                if (run_list(s, n->body, io, budget)) return 1;
        } else if (n->kind == SK_IF) {
            int v = io->read((int)n->a, io->user);
            long c = n->c;
            int ok = n->b == 0 ? v < c : n->b == 1 ? v > c : n->b == 2 ? v <= c : n->b == 3 ? v >= c
                   : n->b == 4 ? v == c : v != c;
            if (io->branch) io->branch((int)n->a, v, ok, io->user);
            if (ok) { if (run_list(s, n->body, io, budget)) return 1; }
            else if (n->other >= 0) { if (run_list(s, n->other, io, budget)) return 1; }
        } else if (n->kind == SK_SHOW) {
            if (io->show((int)n->a, io->read((int)n->a, io->user), io->user)) return 1;
        } else {
            if (io->act(n, io->user)) return 1;
        }
    }
    return 0;
}

int script_run(const Script *s, const ScriptIO *io) {
    long budget = MAX_STEPS;
    return run_list(s, s->first, io, &budget);
}
