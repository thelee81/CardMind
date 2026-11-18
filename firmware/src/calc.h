// Finds the first arithmetic expression in a question and solves it exactly.
// Mirror of calc_line() in pipeline/lib/kbtext.py.
#pragma once

#ifdef __cplusplus
extern "C" {
#endif

// Writes e.g. "Calculator: 17 / 5 = 3.4 (or 3 remainder 2)." Returns 1 if found, else 0.
int calc_line(const char *text, char *out, int outsize);

#ifdef __cplusplus
}
#endif
