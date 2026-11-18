// Calculator. Mirror of calc_line() in pipeline/lib/kbtext.py (keep the two identical).
//
// - "3/4" (slash with digits on both sides) is a fraction; "17 / 5" or "17 divided by 5" is division.
// - "2 3/4" is a mixed number, "25%" or "25 percent" a percentage. A fraction or mixed number is
//   one operand, so "1 2/3 divided by 1/3" is (1 2/3) / (1/3).
// - "of" means times after a fraction, mixed number or percentage ("3/4 of 20", "25% of 80").
// - With a fraction or mixed number (and no decimals or percentages) the answer is exact, in
//   simplest form: "Calculator: 3/4 + 1/8 = 7/8 (or 0.875)." Otherwise decimals.
// - A fraction or mixed number on its own is converted: "11/4 = 2 3/4 (or 2.75)", "2 2/5 = 12/5".
#include "calc.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { T_NUM, T_WORD, T_OP, T_PCT, T_BREAK };
// Packed small (32 bytes): 96 of these live on the loop task's 8 KB stack during calc_line.
typedef struct { double num; char kind, dec, op, tight; char word[16]; } Tok;
#define MAX_TOK 96
#define MAX_VALS 6
#define FRAC_LIMIT 1e12  // bigger numerators/denominators fall back to decimals
#define PROD_LIMIT 1e15  // products are checked in double first, so long long never overflows

enum { K_NUM, K_FRAC, K_MIXED, K_PCT };
typedef struct {
    double v;
    int has_rat;
    long long rn, rd;
    char disp[48];
    int next, kind;
} Val;

static int isdig(char c) { return c >= '0' && c <= '9'; }
static int islow(char c) { return c >= 'a' && c <= 'z'; }
static int ishex(char c) { return isdig(c) || (c >= 'a' && c <= 'f'); }
static char lower(char c) { return (c >= 'A' && c <= 'Z') ? (char)(c + 32) : c; }

static int lex(const char *src, Tok *toks) {
    char t[512];
    int n = 0, nt = 0;
    while (src[n] && n < (int)sizeof(t) - 1) { t[n] = lower(src[n]); n++; }
    t[n] = 0;
    int i = 0;
    while (i < n && nt < MAX_TOK) {
        char c = t[i];
        if (c == '0' && i + 2 < n && t[i + 1] == 'x' && ishex(t[i + 2])) {  // hex like 0x20, not "0 x 20"
            int j = i + 2;
            while (j < n && ishex(t[j])) j++;
            toks[nt].kind = T_BREAK; nt++;
            i = j;
        } else if (isdig(c)) {
            char d[64];
            int nd = 0, j = i;
            while (j < n && isdig(t[j]) && nd < 60) d[nd++] = t[j++];
            while (j + 3 < n && t[j] == ',' && isdig(t[j + 1]) && isdig(t[j + 2]) && isdig(t[j + 3]) &&
                   (j + 4 >= n || !isdig(t[j + 4])) && nd < 57) {
                d[nd++] = t[j + 1]; d[nd++] = t[j + 2]; d[nd++] = t[j + 3];
                j += 4;
            }
            toks[nt].dec = 0;
            if (j + 1 < n && t[j] == '.' && isdig(t[j + 1])) {
                toks[nt].dec = 1;
                d[nd++] = t[j++];
                while (j < n && isdig(t[j]) && nd < 62) d[nd++] = t[j++];
            }
            d[nd] = 0;
            toks[nt].kind = T_NUM;
            toks[nt].num = strtod(d, NULL);
            nt++;
            i = j;
        } else if (islow(c)) {
            int j = i, k = 0;
            while (j < n && islow(t[j])) { if (k < 15) toks[nt].word[k++] = t[j]; j++; }
            toks[nt].word[k] = 0;
            if (j - i > 15) toks[nt].word[0] = '#';  // long words can never be operators
            toks[nt].kind = T_WORD;
            nt++;
            i = j;
        } else if (c == '+' || c == '-' || c == '*' || c == '/') {
            toks[nt].kind = T_OP; toks[nt].op = c;
            toks[nt].tight = c == '/' && i > 0 && isdig(t[i - 1]) && i + 1 < n && isdig(t[i + 1]);
            nt++; i++;
        } else if (c == '%') {
            toks[nt].kind = T_PCT; nt++; i++;
        } else if (c == ' ') {
            i++;
        } else {
            toks[nt].kind = T_BREAK; nt++; i++;
        }
    }
    // word operators
    int m = 0;
    for (int k = 0; k < nt; k++) {
        Tok tk = toks[k];
        if (tk.kind == T_WORD && k + 1 < nt && toks[k + 1].kind == T_WORD) {
            const char *a = tk.word, *b = toks[k + 1].word;
            char op = 0;
            if (!strcmp(a, "multiplied") && !strcmp(b, "by")) op = '*';
            else if (!strcmp(a, "divided") && !strcmp(b, "by")) op = '/';
            else if (!strcmp(a, "take") && !strcmp(b, "away")) op = '-';
            if (op) { toks[m].kind = T_OP; toks[m].op = op; toks[m].tight = 0; m++; k++; continue; }
        }
        if (tk.kind == T_WORD) {
            char op = 0;
            if (!strcmp(tk.word, "plus")) op = '+';
            else if (!strcmp(tk.word, "minus")) op = '-';
            else if (!strcmp(tk.word, "times") || !strcmp(tk.word, "x")) op = '*';
            if (op) { toks[m].kind = T_OP; toks[m].op = op; toks[m].tight = 0; m++; continue; }
        }
        toks[m++] = tk;
    }
    return m;
}

static void fmt(double v, char *out, int size) {
    if (fabs(v - nearbyint(v)) < 1e-9 && fabs(v) < 1e15) {
        snprintf(out, (size_t)size, "%lld", (long long)llround(v));
        return;
    }
    snprintf(out, (size_t)size, "%.3f", v);
    int n = (int)strlen(out);
    while (n > 0 && out[n - 1] == '0') out[--n] = 0;
    if (n > 0 && out[n - 1] == '.') out[--n] = 0;
}

// Number, mixed number, fraction or percentage at toks[j]. Returns 0 if there is none.
static int operand(const Tok *toks, int n, int j, Val *o) {
    if (j >= n || toks[j].kind != T_NUM) return 0;
    double v = toks[j].num;
    int dec = toks[j].dec;
    char a_s[24], b_s[24], v_s[24];
    fmt(v, v_s, sizeof(v_s));
    o->has_rat = 0;
    if (j + 3 < n && toks[j + 1].kind == T_NUM && toks[j + 2].kind == T_OP && toks[j + 2].op == '/' &&
        toks[j + 2].tight && toks[j + 3].kind == T_NUM && !dec && !toks[j + 1].dec && !toks[j + 3].dec &&
        toks[j + 1].num < toks[j + 3].num) {
        double a = toks[j + 1].num, b = toks[j + 3].num;
        if (v * b + a <= FRAC_LIMIT && b <= FRAC_LIMIT) {
            o->has_rat = 1;
            o->rn = (long long)v * (long long)b + (long long)a;
            o->rd = (long long)b;
        }
        fmt(a, a_s, sizeof(a_s));
        fmt(b, b_s, sizeof(b_s));
        o->v = v + a / b;
        snprintf(o->disp, sizeof(o->disp), "%s %s/%s", v_s, a_s, b_s);
        o->next = j + 4;
        o->kind = K_MIXED;
        return 1;
    }
    if (j + 2 < n && toks[j + 1].kind == T_OP && toks[j + 1].op == '/' && toks[j + 1].tight &&
        toks[j + 2].kind == T_NUM && !dec && !toks[j + 2].dec && toks[j + 2].num > 0) {
        double b = toks[j + 2].num;
        if (v <= FRAC_LIMIT && b <= FRAC_LIMIT) {
            o->has_rat = 1;
            o->rn = (long long)v;
            o->rd = (long long)b;
        }
        fmt(b, b_s, sizeof(b_s));
        o->v = v / b;
        snprintf(o->disp, sizeof(o->disp), "%s/%s", v_s, b_s);
        o->next = j + 3;
        o->kind = K_FRAC;
        return 1;
    }
    if (j + 1 < n && (toks[j + 1].kind == T_PCT || (toks[j + 1].kind == T_WORD && !strcmp(toks[j + 1].word, "percent")))) {
        o->v = v / 100;
        snprintf(o->disp, sizeof(o->disp), "%s%%", v_s);
        o->next = j + 2;
        o->kind = K_PCT;
        return 1;
    }
    if (!dec && v <= FRAC_LIMIT) {
        o->has_rat = 1;
        o->rn = (long long)v;
        o->rd = 1;
    }
    o->v = v;
    snprintf(o->disp, sizeof(o->disp), "%s", v_s);
    o->next = j + 1;
    o->kind = K_NUM;
    return 1;
}

static int big(long long x, long long y) { return fabs((double)x) * fabs((double)y) > PROD_LIMIT; }

static long long gcdll(long long a, long long b) {
    if (a < 0) a = -a;
    if (b < 0) b = -b;
    while (b) { long long t = a % b; a = b; b = t; }
    return a;
}

static void red(long long *n, long long *d) {
    if (*d < 0) { *n = -*n; *d = -*d; }
    long long g = gcdll(*n, *d);
    if (!g) g = 1;
    *n /= g;
    *d /= g;
}

// Exact fraction result. Returns 1 ok, 0 division by zero, -1 overflow (use decimals).
static int rat_eval(const Val *vals, const char *ops, int no, long long *on, long long *od) {
    long long tn[MAX_VALS], td[MAX_VALS];
    char signs[MAX_VALS];
    int nterm = 1, nsign = 0;
    tn[0] = vals[0].rn; td[0] = vals[0].rd;
    for (int k = 0; k < no; k++) {
        long long rn = vals[k + 1].rn, rd = vals[k + 1].rd;
        if (ops[k] == '*' || ops[k] == '/') {
            if (ops[k] == '/') {
                if (rn == 0) return 0;
                long long t = rn; rn = rd; rd = t;
            }
            long long *a = &tn[nterm - 1], *b = &td[nterm - 1];
            if (big(*a, rn) || big(*b, rd)) return -1;
            *a *= rn;
            *b *= rd;
            red(a, b);
        } else {
            signs[nsign++] = ops[k];
            tn[nterm] = rn; td[nterm] = rd; nterm++;
        }
    }
    long long n = tn[0], d = td[0];
    for (int k = 0; k < nsign; k++) {
        long long rn = tn[k + 1], rd = td[k + 1];
        if (big(n, rd) || big(rn, d) || big(d, rd)) return -1;
        long long a = n * rd, b = rn * d;
        n = signs[k] == '+' ? a + b : a - b;
        d = d * rd;
        red(&n, &d);
    }
    *on = n;
    *od = d;
    return 1;
}

static void frac_str(long long n, long long d, char *out, int size) {
    if (d == 1) { snprintf(out, (size_t)size, "%lld", n); return; }
    const char *sign = n < 0 ? "-" : "";
    long long m = n < 0 ? -n : n, w = m / d, r = m % d;
    if (w) snprintf(out, (size_t)size, "%s%lld %lld/%lld", sign, w, r, d);
    else snprintf(out, (size_t)size, "%s%lld/%lld", sign, r, d);
}

// " (or 0.875)" when the fraction has an exact decimal of at most 3 places; else "".
static void dec_alt(long long n, long long d, char *out, int size) {
    out[0] = 0;
    if (d != 1 && 1000 % d == 0) {
        char buf[32];
        fmt((double)n / (double)d, buf, sizeof(buf));
        snprintf(out, (size_t)size, " (or %s)", buf);
    }
}

// A fraction or mixed number on its own. Returns 1 and writes the line, or 0.
static int convert(const Val *v, char *out, int outsize) {
    if (!v->has_rat || (v->kind != K_FRAC && v->kind != K_MIXED)) return 0;
    long long n = v->rn, d = v->rd;
    red(&n, &d);
    char res[64], alt[40];
    dec_alt(n, d, alt, sizeof(alt));
    if (v->kind == K_MIXED) {
        snprintf(res, sizeof(res), "%lld/%lld", n, d);
    } else {
        frac_str(n, d, res, sizeof(res));
        if (!strcmp(res, v->disp)) {  // already in simplest form: only the decimal is new
            if (!alt[0]) return 0;
            int len = (int)strlen(alt);
            snprintf(out, (size_t)outsize, "Calculator: %s = %.*s.", v->disp, len - 6, alt + 5);
            return 1;
        }
    }
    snprintf(out, (size_t)outsize, "Calculator: %s = %s%s.", v->disp, res, alt);
    return 1;
}

int calc_line(const char *text, char *out, int outsize) {
    Tok toks[MAX_TOK];
    int nt = lex(text, toks);
    int i = 0;
    while (i < nt) {
        Val vals[MAX_VALS];
        char ops[MAX_VALS], opdisp[MAX_VALS][4];
        int tight[MAX_VALS];
        if (!operand(toks, nt, i, &vals[0])) { i++; continue; }
        int nv = 1, no = 0, j = vals[0].next;
        while (nv < MAX_VALS && j < nt) {
            const Tok *t = &toks[j];
            char op;
            const char *disp;
            int tg = 0;
            if (t->kind == T_OP) {
                op = t->op;
                disp = op == '*' ? "x" : op == '+' ? "+" : op == '-' ? "-" : "/";
                tg = t->tight;
            } else if (t->kind == T_WORD && !strcmp(t->word, "of") &&
                       (vals[nv - 1].kind == K_PCT || vals[nv - 1].kind == K_FRAC || vals[nv - 1].kind == K_MIXED)) {
                op = '*';
                disp = "of";
            } else {
                break;
            }
            if (!operand(toks, nt, j + 1, &vals[nv])) break;
            ops[no] = op;
            snprintf(opdisp[no], sizeof(opdisp[no]), "%s", disp);
            tight[no] = tg;
            no++;
            j = vals[nv].next;
            nv++;
        }
        if (no == 0) {
            if (convert(&vals[0], out, outsize)) return 1;
            i = vals[0].next;
            continue;
        }
        char expr[320];
        int el = snprintf(expr, sizeof(expr), "%s", vals[0].disp);
        for (int k = 0; k < no && el < (int)sizeof(expr); k++) {
            if (tight[k]) el += snprintf(expr + el, sizeof(expr) - (size_t)el, "/%s", vals[k + 1].disp);
            else el += snprintf(expr + el, sizeof(expr) - (size_t)el, " %s %s", opdisp[k], vals[k + 1].disp);
        }
        int frac = 0, all_rat = 1;
        for (int k = 0; k < nv; k++) {
            if (vals[k].kind == K_FRAC || vals[k].kind == K_MIXED) frac = 1;
            if (!vals[k].has_rat) all_rat = 0;
        }
        if (frac && all_rat) {
            long long rn, rd;
            int st = rat_eval(vals, ops, no, &rn, &rd);
            if (st == 0) return 0;
            if (st == 1) {
                char res[64], alt[40];
                frac_str(rn, rd, res, sizeof(res));
                dec_alt(rn, rd, alt, sizeof(alt));
                snprintf(out, (size_t)outsize, "Calculator: %s = %s%s.", expr, res, alt);
                return 1;
            }
        }
        // decimals: * and / first, left to right
        double terms[MAX_VALS];
        char signs[MAX_VALS];
        int nterm = 1, nsign = 0;
        terms[0] = vals[0].v;
        for (int k = 0; k < no; k++) {
            double x = vals[k + 1].v;
            if (ops[k] == '*') terms[nterm - 1] *= x;
            else if (ops[k] == '/') { if (x == 0) return 0; terms[nterm - 1] /= x; }
            else { signs[nsign++] = ops[k]; terms[nterm++] = x; }
        }
        double res = terms[0];
        for (int k = 0; k < nsign; k++) res = signs[k] == '+' ? res + terms[k + 1] : res - terms[k + 1];

        char buf[48];
        fmt(res, buf, sizeof(buf));
        int len = snprintf(out, (size_t)outsize, "Calculator: %s = %s", expr, buf);
        double a = vals[0].v, b = vals[nv - 1].v;
        if (no == 1 && ops[0] == '/' && vals[0].kind == K_NUM && vals[1].kind == K_NUM && a == floor(a) &&
            b == floor(b) && a >= 0 && b > 0 && a < 9e15 && ((long long)a % (long long)b) != 0 && len < outsize)
            len += snprintf(out + len, (size_t)(outsize - len), " (or %lld remainder %lld)",
                            (long long)a / (long long)b, (long long)a % (long long)b);
        if (len < outsize) snprintf(out + len, (size_t)(outsize - len), ".");
        return 1;
    }
    return 0;
}
