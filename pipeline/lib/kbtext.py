"""Text rules shared with the firmware.

Everything in this file has a C twin (firmware/src/kb.c, calc.c, chat.c).
Training data is built with these exact functions, so what the model sees in
training is what it will see on the device. If you change a rule here, change
the C side too and re-run pipeline/verify.py.
"""
import math
import struct
import unicodedata

# ------------------------------------------------------------------ ASCII folding
_REPL = {
    "×": " x ", "÷": " / ", "−": "-", "–": "-", "—": " - ",
    "‘": "'", "’": "'", "“": '"', "”": '"', "…": "...",
    "°": " degrees ", "½": "1/2", "¼": "1/4", "¾": "3/4",
    "²": "^2", "³": "^3", "•": "-", " ": " ", "→": "->",
}


def ascii_fold(s: str) -> str:
    """Map text to printable ASCII on one line (the Cardputer font is ASCII)."""
    for k, v in _REPL.items():
        s = s.replace(k, v)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = "".join(c if 32 <= ord(c) < 127 else " " for c in s)
    return " ".join(s.split())


# ------------------------------------------------------------------ retrieval words
STOPWORDS = sorted(set("""
a an the and or but if of to in on at by for with from as is are was were be been
being it its this that these those there here what which who whom whose when where
why how do does did doing done can could will would should may might must shall i
you he she we they me him her us them my your his our their mine yours am not no so
than then too very just also into about up down out over under again more most some
any each other such only own same don isn aren wasn weren hasn haven hadn doesn didn
won wouldn shouldn ll re ve let lets please tell explain show give know want like
okay ok hi hello hey thanks thank yes yeah um uh hmm bolt
""".split()))
_STOP = set(STOPWORDS)
MAX_WORD = 32


def words(text: str):
    """Retrieval tokens: lowercase [a-z0-9] runs, stopwords dropped, light plural strip."""
    out, cur = [], []
    for ch in text.lower() + " ":
        if ("a" <= ch <= "z") or ("0" <= ch <= "9"):
            cur.append(ch)
            continue
        if cur:
            w = "".join(cur)[:MAX_WORD]
            cur = []
            if len(w) < 2 and not w.isdigit():
                continue
            if w in _STOP:
                continue
            if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
                w = w[:-1]
            out.append(w)
    return out


def fnv1a(s: str) -> int:
    h = 0x811C9DC5
    for b in s.encode("ascii"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


class BM25Index:
    """BM25 over word hashes (hash collisions are merged, same as on the device)."""

    K1, B = 1.2, 0.75

    def __init__(self, passages):
        self.passages = passages
        n = len(passages)
        tfs, lens = [], []
        df = {}
        for p in passages:
            tf = {}
            ws = words(p)
            for w in ws:
                h = fnv1a(w)
                tf[h] = tf.get(h, 0) + 1
            tfs.append(tf)
            lens.append(len(ws))
            for h in tf:
                df[h] = df.get(h, 0) + 1
        avgdl = (sum(lens) / n) if n else 1.0
        self.postings = {}  # hash -> list[(pid, weight float32)]
        for pid, tf in enumerate(tfs):
            norm = self.K1 * (1 - self.B + self.B * lens[pid] / max(avgdl, 1e-6))
            for h, f in tf.items():
                idf = math.log(1 + (n - df[h] + 0.5) / (df[h] + 0.5))
                w = idf * f * (self.K1 + 1) / (f + norm)
                w = struct.unpack("<f", struct.pack("<f", w))[0]  # same precision as kb.bin
                self.postings.setdefault(h, []).append((pid, w))

    def search(self, query: str):
        """Return (score, passage_id) of the best passage, or (0.0, -1)."""
        scores = {}
        seen = set()
        for w in words(query):
            h = fnv1a(w)
            if h in seen:
                continue
            seen.add(h)
            for pid, wt in self.postings.get(h, ()):
                scores[pid] = scores.get(pid, 0.0) + wt
        if not scores:
            return 0.0, -1
        pid = min(scores, key=lambda p: (-scores[p], p))  # ties -> lowest id (C does the same)
        return scores[pid], pid

    def write_bin(self, path, min_score, n_buckets):
        """Serialize for firmware/src/kb.c (little-endian, layout documented there)."""
        terms = sorted(self.postings, key=lambda h: (h % n_buckets, h))
        header_size = 64
        stop_blob = (" ".join(STOPWORDS)).encode("ascii")
        off_buckets = header_size
        off_terms = off_buckets + 4 * (n_buckets + 1)
        off_postings = off_terms + 12 * len(terms)
        posting_blob = bytearray()
        term_blob = bytearray()
        for h in terms:
            plist = self.postings[h]
            term_blob += struct.pack("<III", h, len(plist), off_postings + len(posting_blob))
            for pid, w in plist:
                posting_blob += struct.pack("<If", pid, w)
        off_pidx = off_postings + len(posting_blob)
        texts = [p.encode("ascii") for p in self.passages]
        off_text = off_pidx + 4 * (len(texts) + 1)
        pidx, pos = [], off_text
        for t in texts:
            pidx.append(pos)
            pos += len(t)
        pidx.append(pos)
        off_stop = pos
        bucket_start = [0] * (n_buckets + 1)
        for h in terms:
            bucket_start[h % n_buckets + 1] += 1
        for i in range(n_buckets):
            bucket_start[i + 1] += bucket_start[i]
        header = struct.pack("<4sIIIIfIIIIII", b"EKB1", 1, len(texts), n_buckets, len(terms),
                             float(min_score), off_buckets, off_terms, off_pidx, off_text,
                             off_stop, len(stop_blob))
        header = header.ljust(header_size, b"\0")
        with open(path, "wb") as f:
            f.write(header)
            f.write(struct.pack(f"<{n_buckets + 1}I", *bucket_start))
            f.write(term_blob)
            f.write(posting_blob)
            f.write(struct.pack(f"<{len(pidx)}I", *pidx))
            for t in texts:
                f.write(t)
            f.write(stop_blob)


# ------------------------------------------------------------------ calculator
# Mirror of firmware/src/calc.c. Rules:
# - "3/4" (slash with digits on both sides) is a fraction; "17 / 5" or "17 divided by 5" is division.
# - "2 3/4" is a mixed number, "25%" or "25 percent" a percentage. A fraction or mixed number is
#   one operand, so "1 2/3 divided by 1/3" is (1 2/3) / (1/3).
# - "of" means times after a fraction, mixed number or percentage ("3/4 of 20", "25% of 80").
# - A fraction or mixed number on its own is converted: "11/4 = 2 3/4 (or 2.75)", "2 2/5 = 12/5".
# - With a fraction or mixed number (and no decimals or percentages) the answer is exact, in
#   simplest form: "Calculator: 3/4 + 1/8 = 7/8 (or 0.875)." Otherwise decimals, as before.
FRAC_LIMIT = 1e12      # bigger numerators/denominators fall back to decimals
PROD_LIMIT = 1e15      # products are checked in floating point first, so C long long never overflows


def _fmt(v: float) -> str:
    if abs(v - round(v)) < 1e-9 and abs(v) < 1e15:
        return "%d" % int(round(v))
    s = "%.3f" % v
    return s.rstrip("0").rstrip(".")


def _lex(text: str):
    """Tokens: ["N", value, is_decimal] ["O", op, tight] ["W", word] ["P"] (percent) ["B"] (break)."""
    t = text.lower()
    toks, i, n = [], 0, len(t)
    while i < n:
        c = t[i]
        if c == "0" and i + 2 < n and t[i + 1] == "x" and t[i + 2] in "0123456789abcdef":
            j = i + 2  # hex like 0x20 (an IR code), not "0 x 20"
            while j < n and t[j] in "0123456789abcdef":
                j += 1
            toks.append(["B"])
            i = j
        elif c.isdigit():
            j = i
            digits = []
            while j < n and t[j].isdigit():
                digits.append(t[j]); j += 1
            # thousands separators: 12,345
            while (j + 3 < n and t[j] == "," and t[j + 1:j + 4].isdigit()
                   and (j + 4 >= n or not t[j + 4].isdigit())):
                digits.extend(t[j + 1:j + 4]); j += 4
            dec = False
            if j + 1 < n and t[j] == "." and t[j + 1].isdigit():
                dec = True
                digits.append("."); j += 1
                while j < n and t[j].isdigit():
                    digits.append(t[j]); j += 1
            toks.append(["N", float("".join(digits)), dec])
            i = j
        elif "a" <= c <= "z":
            j = i
            while j < n and "a" <= t[j] <= "z":
                j += 1
            toks.append(["W", t[i:j]])
            i = j
        elif c in "+-*/":
            tight = c == "/" and i > 0 and t[i - 1].isdigit() and i + 1 < n and t[i + 1].isdigit()
            toks.append(["O", c, tight]); i += 1
        elif c == "%":
            toks.append(["P"]); i += 1
        elif c == " ":
            i += 1
        else:
            toks.append(["B"]); i += 1
    # word operators
    out, i = [], 0
    single = {"plus": "+", "minus": "-", "times": "*", "x": "*"}
    double = {("multiplied", "by"): "*", ("divided", "by"): "/", ("take", "away"): "-"}
    while i < len(toks):
        k = toks[i][0]
        if k == "W" and i + 1 < len(toks) and toks[i + 1][0] == "W" and (toks[i][1], toks[i + 1][1]) in double:
            out.append(["O", double[(toks[i][1], toks[i + 1][1])], False]); i += 2; continue
        if k == "W" and toks[i][1] in single:
            out.append(["O", single[toks[i][1]], False]); i += 1; continue
        out.append(toks[i]); i += 1
    return out


def _operand(toks, j):
    """Number, mixed number, fraction or percentage at toks[j]: dict(v, rat, disp, next, kind)."""
    n = len(toks)
    if j >= n or toks[j][0] != "N":
        return None
    v, dec = toks[j][1], toks[j][2]
    if (j + 3 < n and toks[j + 1][0] == "N" and toks[j + 2][0] == "O" and toks[j + 2][1] == "/"
            and toks[j + 2][2] and toks[j + 3][0] == "N" and not dec and not toks[j + 1][2]
            and not toks[j + 3][2] and toks[j + 1][1] < toks[j + 3][1]):
        a, b = toks[j + 1][1], toks[j + 3][1]
        rat = None
        if v * b + a <= FRAC_LIMIT and b <= FRAC_LIMIT:
            rat = (int(v) * int(b) + int(a), int(b))
        return {"v": v + a / b, "rat": rat, "disp": _fmt(v) + " " + _fmt(a) + "/" + _fmt(b),
                "next": j + 4, "kind": "mixed"}
    if (j + 2 < n and toks[j + 1][0] == "O" and toks[j + 1][1] == "/" and toks[j + 1][2]
            and toks[j + 2][0] == "N" and not dec and not toks[j + 2][2] and toks[j + 2][1] > 0):
        b = toks[j + 2][1]
        rat = (int(v), int(b)) if v <= FRAC_LIMIT and b <= FRAC_LIMIT else None
        return {"v": v / b, "rat": rat, "disp": _fmt(v) + "/" + _fmt(b), "next": j + 3, "kind": "frac"}
    if j + 1 < n and (toks[j + 1][0] == "P" or (toks[j + 1][0] == "W" and toks[j + 1][1] == "percent")):
        return {"v": v / 100, "rat": None, "disp": _fmt(v) + "%", "next": j + 2, "kind": "pct"}
    rat = (int(v), 1) if not dec and v <= FRAC_LIMIT else None
    return {"v": v, "rat": rat, "disp": _fmt(v), "next": j + 1, "kind": "num"}


class _Overflow(Exception):
    pass


def _big(x, y):
    return abs(float(x)) * abs(float(y)) > PROD_LIMIT


def _red(n, d):
    if d < 0:
        n, d = -n, -d
    g = math.gcd(n, d) or 1
    return (n // g, d // g)


def _rat_eval(vals, ops):
    """Exact fraction result (n, d), or None on division by zero. Raises _Overflow."""
    def mul(a, b):
        if _big(a[0], b[0]) or _big(a[1], b[1]):
            raise _Overflow
        return _red(a[0] * b[0], a[1] * b[1])

    terms, signs = [vals[0]["rat"]], []
    for (op, _, _), v in zip(ops, vals[1:]):
        r = v["rat"]
        if op == "*":
            terms[-1] = mul(terms[-1], r)
        elif op == "/":
            if r[0] == 0:
                return None
            terms[-1] = mul(terms[-1], (r[1], r[0]))
        else:
            signs.append(op); terms.append(r)
    res = terms[0]
    for op, r in zip(signs, terms[1:]):
        if _big(res[0], r[1]) or _big(r[0], res[1]) or _big(res[1], r[1]):
            raise _Overflow
        a, b = res[0] * r[1], r[0] * res[1]
        res = _red(a + b if op == "+" else a - b, res[1] * r[1])
    return res


def _frac_str(n, d):
    if d == 1:
        return "%d" % n
    sign, m = ("-" if n < 0 else ""), abs(n)
    w, r = m // d, m % d
    return sign + ("%d %d/%d" % (w, r, d) if w else "%d/%d" % (r, d))


def _dec_alt(r):
    """' (or 0.875)' when the fraction has an exact decimal of at most 3 places."""
    return " (or " + _fmt(r[0] / r[1]) + ")" if r[1] != 1 and 1000 % r[1] == 0 else ""


def _convert(v):
    """A fraction or mixed number on its own: simplest / mixed form, or improper form."""
    if v["rat"] is None or v["kind"] not in ("frac", "mixed"):
        return None
    r = _red(*v["rat"])
    if v["kind"] == "mixed":
        res = "%d/%d" % r
    else:
        res = _frac_str(*r)
        if res == v["disp"]:  # already in simplest form: only the decimal is new
            alt = _dec_alt(r)
            return "Calculator: " + v["disp"] + " = " + alt[5:-1] + "." if alt else None
    return "Calculator: " + v["disp"] + " = " + res + _dec_alt(r) + "."


def calc_line(text: str):
    """Find the first arithmetic expression in a question and solve it exactly.

    Returns e.g. 'Calculator: 17 / 5 = 3.4 (or 3 remainder 2).' or
    'Calculator: 3/4 of 20 = 15.' or None.
    """
    toks = _lex(text)
    i = 0
    while i < len(toks):
        first = _operand(toks, i)
        if first is None:
            i += 1
            continue
        vals, ops, j = [first], [], first["next"]
        while len(vals) < 6 and j < len(toks):
            t = toks[j]
            if t[0] == "O":
                op = (t[1], "x" if t[1] == "*" else t[1], t[2])
            elif t[0] == "W" and t[1] == "of" and vals[-1]["kind"] in ("pct", "frac", "mixed"):
                op = ("*", "of", False)
            else:
                break
            nxt = _operand(toks, j + 1)
            if nxt is None:
                break
            ops.append(op); vals.append(nxt); j = nxt["next"]
        if not ops:
            line = _convert(first)
            if line:
                return line
            i = first["next"]
            continue
        expr = vals[0]["disp"]
        for (_, disp, tight), v in zip(ops, vals[1:]):
            expr += ("/" if tight else " " + disp + " ") + v["disp"]
        frac = (any(v["kind"] in ("frac", "mixed") for v in vals)
                and all(v["rat"] is not None for v in vals))
        if frac:
            try:
                r = _rat_eval(vals, ops)
            except _Overflow:
                frac = False
            else:
                if r is None:
                    return None
                return "Calculator: " + expr + " = " + _frac_str(*r) + _dec_alt(r) + "."
        # decimals: * and / first, left to right
        terms, signs = [vals[0]["v"]], []
        for (op, _, _), v in zip(ops, vals[1:]):
            x = v["v"]
            if op == "*":
                terms[-1] = terms[-1] * x
            elif op == "/":
                if x == 0:
                    return None
                terms[-1] = terms[-1] / x
            else:
                signs.append(op); terms.append(x)
        res = terms[0]
        for op, x in zip(signs, terms[1:]):
            res = res + x if op == "+" else res - x
        line = "Calculator: " + expr + " = " + _fmt(res)
        a, b = vals[0]["v"], vals[-1]["v"]
        if (len(ops) == 1 and ops[0][0] == "/" and vals[0]["kind"] == "num" and vals[1]["kind"] == "num"
                and a == int(a) and b == int(b) and a >= 0 and b > 0 and a < 9e15 and int(a) % int(b) != 0):
            line += " (or %d remainder %d)" % (int(a) // int(b), int(a) % int(b))
        return line + "."
    return None


SCRIPT_MODE = "Mode: script."  # ctx for Card script requests (same text in firmware/src/chat.c)


def build_ctx(user_text: str, index, min_score: float, status=None):
    """The <ctx> text for one user turn: device line, calculator line and/or best passage.

    status: a devtext.DevStatus (the device's readings); None means devtext.example_status().
    Actions update it (brightness, volume), like the real device. Returns None if there is no ctx.
    """
    from .devtext import dev_commit, dev_line, dev_parse, dev_plan, example_status
    parts = []
    r = dev_parse(user_text)
    if r.script:  # the model writes one "Script:" line; no card, no calculator
        from .devtext import script_hints
        h = script_hints(user_text)
        return SCRIPT_MODE + (" " + h if h else "")
    if r.intent:
        st = status if status is not None else example_status()
        dev_plan(r, st)
        parts.append(dev_line(r, st))
        dev_commit(st)
    c = calc_line(user_text)
    if c:
        parts.append(c)
    if index is not None and not r.intent:  # with a Device line the card is left out (it distracts)
        score, pid = index.search(user_text)
        if pid >= 0 and score >= min_score:
            parts.append(index.passages[pid])
    return " ".join(parts) if parts else None
