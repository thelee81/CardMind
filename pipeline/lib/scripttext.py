"""Card scripts: a tiny language of the Cardputer's own actions and readings.

Python twin of firmware/src/script.c (keep the two identical, then run pipeline/verify.py).

  repeat 5 { led red; wait 300; led off; wait 300 }
  if battery < 20 { beep 1000 500 } else { show battery }

Statements (separated by ";"):
  led COLOR            off red green blue white yellow orange purple pink cyan magenta
  bright N             screen brightness 10..100 (%)
  vol N                speaker volume 0..100 (%)
  beep [HZ [MS]]       HZ 100..8000 (default 2000), MS 10..2000 (default 200)
  ir ADDR CMD          NEC infrared, 0..255 each (decimal or 0x hex)
  wait MS              1..60000
  show READING         print a reading on screen
  sound NAME           RLCD board: chime woof ribbit tweet honk ring ufo thunder roar notify startup
  face NAME            RLCD board: the eyes' emotion (normal = automatic) happy sad angry surprised ...
  repeat N { ... }     N 1..100
  if READING OP N { ... } [else { ... }]     OP: < > <= >= == !=
READING: battery (%), temp (C), mic (dBFS), ram (KB free), uptime (s), bright (%), vol (%),
         room (C, RLCD SHTC3), humid (% relative humidity, RLCD)

Limits: 200 characters, 48 statements, 4 nested blocks, worst case 2000 steps and 10 minutes.
parse() returns (program, None) or (None, "error message"). The model writes "Script: <script>".
"""

MAX_CHARS = 200
MAX_NODES = 48
MAX_DEPTH = 4
MAX_STEPS = 2000
MAX_MS = 600000
MIC_MS = 600  # a microphone reading takes this long

COLORS = ["off", "red", "green", "blue", "white", "yellow", "orange", "purple", "pink", "cyan", "magenta"]
READINGS = ["battery", "temp", "mic", "ram", "uptime", "bright", "vol", "room", "humid"]
SOUNDS = ["chime", "woof", "ribbit", "tweet", "honk", "ring", "ufo", "thunder", "roar", "notify", "startup"]
FACES = ["normal", "happy", "sad", "angry", "surprised", "sleepy", "suspicious", "confused", "love", "curious"]
OPS = ["<", ">", "<=", ">=", "==", "!="]
PREFIX = "Script:"


def _lex(text):
    """Tokens: ("w", word) ("n", int) ("s", symbol) or ("x", char) for anything else."""
    t = text.lower()
    out, i, n = [], 0, len(t)
    while i < n:
        if len(out) >= 127:  # same token limit as the C lexer
            return None
        c = t[i]
        if c == " ":
            i += 1
        elif "a" <= c <= "z":
            j = i
            while j < n and "a" <= t[j] <= "z":
                j += 1
            w = t[i:j]
            out.append(("w", w if len(w) <= 15 else "#" + w[1:15]))  # C keeps 15 chars
            i = j
        elif c == "-" and i + 1 < n and t[i + 1].isdigit():
            j = i + 1
            while j < n and t[j].isdigit():
                j += 1
            if j - i - 1 > 9:
                return None
            out.append(("n", -int(t[i + 1:j])))
            i = j
        elif c.isdigit():
            j = i
            if c == "0" and i + 1 < n and t[i + 1] == "x":
                j = i + 2
                while j < n and t[j] in "0123456789abcdef":
                    j += 1
                digits = t[i + 2:j]
                if not digits or j - i > 10:
                    return None
                out.append(("n", int(digits, 16)))
            else:
                while j < n and t[j].isdigit():
                    j += 1
                if j - i > 9:
                    return None
                out.append(("n", int(t[i:j])))
            i = j
        elif c in "{};":
            out.append(("s", c)); i += 1
        elif c in "<>=!":
            if i + 1 < n and t[i + 1] == "=":
                out.append(("s", t[i:i + 2])); i += 2
            elif c in "<>":
                out.append(("s", c)); i += 1
            else:
                return None
        else:
            return None
    return out


class _P:
    def __init__(self, toks):
        self.t, self.i, self.nodes = toks, 0, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else ("e", None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def num(self, lo, hi, what):
        k, v = self.take()
        if k != "n":
            raise ValueError(f"{what}: number expected")
        if not lo <= v <= hi:
            raise ValueError(f"{what}: {lo} to {hi}")
        return v

    def sym(self, s):
        if self.take() != ("s", s):
            raise ValueError(f"'{s}' expected")

    def block(self, depth):
        self.sym("{")
        body = self.stmts(depth + 1, "}")
        self.sym("}")
        return body

    def stmts(self, depth, end):
        if depth > MAX_DEPTH:
            raise ValueError("too many nested blocks")
        out = [self.stmt(depth)]
        while self.peek() == ("s", ";"):
            self.take()
            if self.peek() == ("s", end) or self.peek()[0] == "e":
                break  # trailing ;
            out.append(self.stmt(depth))
        return out

    def stmt(self, depth):
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise ValueError("script too long")
        k, w = self.take()
        if k != "w":
            raise ValueError("command expected")
        if w == "led":
            k2, c = self.take()
            if k2 != "w" or c not in COLORS:
                raise ValueError("led: colour expected")
            return ("led", COLORS.index(c))
        if w == "bright":
            return ("bright", self.num(10, 100, "bright"))
        if w == "vol":
            return ("vol", self.num(0, 100, "vol"))
        if w == "beep":
            hz, ms = 2000, 200
            if self.peek()[0] == "n":
                hz = self.num(100, 8000, "beep")
                if self.peek()[0] == "n":
                    ms = self.num(10, 2000, "beep")
            return ("beep", hz, ms)
        if w == "ir":
            return ("ir", self.num(0, 255, "ir"), self.num(0, 255, "ir"))
        if w == "wait":
            return ("wait", self.num(1, 60000, "wait"))
        if w == "sound":
            k2, c = self.take()
            if k2 != "w" or c not in SOUNDS:
                raise ValueError("sound: name expected")
            return ("sound", SOUNDS.index(c))
        if w == "face":
            k2, c = self.take()
            if k2 != "w" or c not in FACES:
                raise ValueError("face: name expected")
            return ("face", FACES.index(c))
        if w == "show":
            k2, r = self.take()
            if k2 != "w" or r not in READINGS:
                raise ValueError("show: reading expected")
            return ("show", READINGS.index(r))
        if w == "repeat":
            n = self.num(1, 100, "repeat")
            return ("repeat", n, self.block(depth))
        if w == "if":
            k2, r = self.take()
            if k2 != "w" or r not in READINGS:
                raise ValueError("if: reading expected")
            k3, op = self.take()
            if k3 != "s" or op not in OPS:
                raise ValueError("if: < > <= >= == != expected")
            v = self.num(-1000000, 1000000, "if")
            then = self.block(depth)
            other = None
            if self.peek() == ("w", "else"):
                self.take()
                other = self.block(depth)
            return ("if", READINGS.index(r), OPS.index(op), v, then, other)
        raise ValueError(f"unknown command '{w}'")


def _cost(stmts):
    """Worst-case (steps, milliseconds) of a statement list."""
    steps = ms = 0
    for s in stmts:
        if s[0] == "repeat":
            a, b = _cost(s[2])
            steps += 1 + s[1] * a
            ms += s[1] * b
        elif s[0] == "if":
            a, b = _cost(s[4])
            c, d = _cost(s[5]) if s[5] else (0, 0)
            steps += 1 + max(a, c)
            ms += max(b, d) + (MIC_MS if s[1] == 2 else 0)
        else:
            steps += 1
            ms += s[1] if s[0] == "wait" else s[2] if s[0] == "beep" else MIC_MS if s == ("show", 2) else 0
        steps = min(steps, 10 ** 9)
        ms = min(ms, 10 ** 12)
    return steps, ms


def parse(text):
    """(program, None) or (None, error). program = list of statements (tuples)."""
    if len(text) > MAX_CHARS:
        return None, "script too long"
    toks = _lex(text)
    if toks is None:
        return None, "unexpected character"
    if not toks:
        return None, "empty script"
    p = _P(toks)
    try:
        prog = p.stmts(1, "")
        if p.peek()[0] != "e":
            raise ValueError("';' expected")
    except ValueError as e:
        return None, str(e)
    steps, ms = _cost(prog)
    if steps > MAX_STEPS:
        return None, "too many steps"
    if ms > MAX_MS:
        return None, "runs too long (max 10 minutes)"
    return prog, None


def to_text(stmts):
    """Canonical form: 'repeat 5 { led red; wait 300 }'."""
    out = []
    for s in stmts:
        k = s[0]
        if k == "led":
            out.append("led " + COLORS[s[1]])
        elif k in ("bright", "vol", "wait"):
            out.append(f"{k} {s[1]}")
        elif k == "beep":
            out.append("beep" if (s[1], s[2]) == (2000, 200) else f"beep {s[1]} {s[2]}")
        elif k == "ir":
            out.append(f"ir {s[1]} {s[2]}")
        elif k == "show":
            out.append("show " + READINGS[s[1]])
        elif k == "sound":
            out.append("sound " + SOUNDS[s[1]])
        elif k == "face":
            out.append("face " + FACES[s[1]])
        elif k == "repeat":
            out.append(f"repeat {s[1]} {{ {to_text(s[2])} }}")
        elif k == "if":
            t = f"if {READINGS[s[1]]} {OPS[s[2]]} {s[3]} {{ {to_text(s[4])} }}"
            if s[5]:
                t += f" else {{ {to_text(s[5])} }}"
            out.append(t)
    return "; ".join(out)


def run(stmts, read, act, trace=None, budget=None):
    """Execute with callbacks: read(index) -> int, act(stmt). Returns the trace list (for tests)."""
    trace = [] if trace is None else trace
    budget = budget or [MAX_STEPS]
    for s in stmts:
        if budget[0] <= 0:
            return trace
        budget[0] -= 1
        if s[0] == "repeat":
            for _ in range(s[1]):
                run(s[2], read, act, trace, budget)
        elif s[0] == "if":
            v = read(s[1])
            ok = {0: v < s[3], 1: v > s[3], 2: v <= s[3], 3: v >= s[3], 4: v == s[3], 5: v != s[3]}[s[2]]
            trace.append(f"if {READINGS[s[1]]}={v} {'yes' if ok else 'no'}")
            if ok:
                run(s[4], read, act, trace, budget)
            elif s[5]:
                run(s[5], read, act, trace, budget)
        else:
            if s[0] == "show":
                trace.append(f"show {READINGS[s[1]]}={read(s[1])}")
            else:
                trace.append(act(s))
    return trace


def describe(s):
    """Trace text of one action statement (same in C)."""
    k = s[0]
    if k == "led":
        return "led " + COLORS[s[1]]
    if k == "beep":
        return f"beep {s[1]} {s[2]}"
    if k == "ir":
        return f"ir {s[1]} {s[2]}"
    if k == "sound":
        return "sound " + SOUNDS[s[1]]
    if k == "face":
        return "face " + FACES[s[1]]
    return f"{k} {s[1]}"


EXAMPLE_READINGS = [78, 41, -47, 44, 4980, 100, 50, 27, 61]  # battery temp mic ram uptime bright vol room humid


def check(text):
    """For tests: canonical text and an execution trace with the example readings, or 'ERROR msg'."""
    prog, err = parse(text)
    if err:
        return "ERROR " + err
    tr = run(prog, lambda i: EXAMPLE_READINGS[i], describe)
    return to_text(prog) + " | " + " / ".join(tr[:40])
