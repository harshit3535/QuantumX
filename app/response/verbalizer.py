"""Speech verbalizers.

Raw math and raw code must never go straight to a TTS engine.

  math_to_speech   "x = (-b ± √(b² - 4ac)) / 2a"
                   -> "x equals negative b plus or minus the square root of
                       b squared minus four a c, divided by two a"
  code_summary     a short spoken description of generated code
  code_to_speech   only when the user says "read the code aloud"
  text_to_speech   strips markdown/URLs so the voice does not read symbols
"""
from __future__ import annotations

import re

from ..models import Segment

# =============================================================== vocabulary
WORDS: dict[str, dict[str, str]] = {
    "en": {
        "plus": "plus", "minus": "minus", "pm": "plus or minus", "mp": "minus or plus", "times": "times",
        "div": "divided by", "eq": "equals", "ne": "does not equal", "lt": "is less than", "gt": "is greater than",
        "le": "is less than or equal to", "ge": "is greater than or equal to", "approx": "is approximately",
        "neg": "negative", "pos": "positive", "squared": "squared", "cubed": "cubed", "power": "to the power of",
        "sqrt": "the square root of", "cbrt": "the cube root of", "root": "root", "quantity": "the quantity",
        "abs": "the absolute value of", "fact": "factorial", "percent": "percent", "sub": "sub", "of": "of",
        "sum": "the sum", "prod": "the product", "int": "the integral", "lim": "the limit", "from": "from", "to": "to",
        "as": "as", "approaches": "approaches", "inf": "infinity", "pi": "pi", "and_so_on": "and so on",
        "point": "point", "sin": "sine", "cos": "cosine", "tan": "tangent", "cot": "cotangent", "sec": "secant",
        "csc": "cosecant", "log": "log", "ln": "natural log", "exp": "exponential", "arcsin": "arc sine",
        "arccos": "arc cosine", "arctan": "arc tangent", "sinh": "hyperbolic sine", "cosh": "hyperbolic cosine",
        "tanh": "hyperbolic tangent", "det": "determinant", "min": "minimum", "max": "maximum", "mod": "mod",
        "and": "and", "or": "or", "inverse": "inverse",
    },
    "hi": {
        "plus": "प्लस", "minus": "माइनस", "pm": "प्लस या माइनस", "mp": "माइनस या प्लस", "times": "गुणा", "div": "भाग",
        "eq": "बराबर", "ne": "बराबर नहीं", "lt": "से छोटा", "gt": "से बड़ा", "le": "छोटा या बराबर", "ge": "बड़ा या बराबर",
        "approx": "लगभग बराबर", "neg": "ऋणात्मक", "pos": "धनात्मक", "squared": "का वर्ग", "cubed": "का घन",
        "power": "घात", "sqrt": "वर्गमूल", "cbrt": "घनमूल", "root": "मूल", "quantity": "कोष्ठक",
        "abs": "निरपेक्ष मान", "fact": "फैक्टोरियल", "percent": "प्रतिशत", "sub": "सब", "of": "का",
        "sum": "योग", "prod": "गुणनफल", "int": "समाकलन", "lim": "सीमा", "from": "से", "to": "तक", "as": "जब",
        "approaches": "की ओर जाए", "inf": "अनंत", "pi": "पाई", "and_so_on": "और इसी तरह", "point": "दशमलव",
        "sin": "साइन", "cos": "कोसाइन", "tan": "टैन", "cot": "कॉट", "sec": "सेक", "csc": "कोसेक", "log": "लॉग",
        "ln": "नेचुरल लॉग", "exp": "एक्सपोनेंशियल", "arcsin": "आर्क साइन", "arccos": "आर्क कोसाइन", "arctan": "आर्क टैन",
        "sinh": "साइन एच", "cosh": "कोस एच", "tanh": "टैन एच", "det": "डिटरमिनेंट", "min": "न्यूनतम",
        "max": "अधिकतम", "mod": "मॉड", "and": "और", "or": "या", "inverse": "इन्वर्स",
    },
    "gu": {
        "plus": "વત્તા", "minus": "ઓછા", "pm": "વત્તા અથવા ઓછા", "mp": "ઓછા અથવા વત્તા", "times": "ગુણ", "div": "ભાગ",
        "eq": "બરાબર", "ne": "બરાબર નથી", "lt": "કરતાં નાનું", "gt": "કરતાં મોટું", "le": "નાનું અથવા બરાબર",
        "ge": "મોટું અથવા બરાબર", "approx": "લગભગ બરાબર", "neg": "ઋણ", "pos": "ધન", "squared": "નો વર્ગ",
        "cubed": "નો ઘન", "power": "ઘાત", "sqrt": "વર્ગમૂળ", "cbrt": "ઘનમૂળ", "root": "મૂળ", "quantity": "કૌંસ",
        "abs": "નિરપેક્ષ કિંમત", "fact": "ફેક્ટોરિયલ", "percent": "ટકા", "sub": "સબ", "of": "નું",
        "sum": "સરવાળો", "prod": "ગુણાકાર", "int": "સંકલન", "lim": "લિમિટ", "from": "થી", "to": "સુધી", "as": "જ્યારે",
        "approaches": "તરફ જાય", "inf": "અનંત", "pi": "પાઈ", "and_so_on": "અને એમ આગળ", "point": "દશાંશ",
        "sin": "સાઈન", "cos": "કોસાઈન", "tan": "ટેન", "cot": "કોટ", "sec": "સેક", "csc": "કોસેક", "log": "લોગ",
        "ln": "નેચરલ લોગ", "exp": "એક્સપોનેન્શિયલ", "arcsin": "આર્ક સાઈન", "arccos": "આર્ક કોસાઈન",
        "arctan": "આર્ક ટેન", "sinh": "સાઈન એચ", "cosh": "કોસ એચ", "tanh": "ટેન એચ", "det": "ડિટરમિનન્ટ",
        "min": "લઘુત્તમ", "max": "મહત્તમ", "mod": "મોડ", "and": "અને", "or": "અથવા", "inverse": "ઇન્વર્સ",
    },
}

_GREEK = {
    "alpha": "alpha", "beta": "beta", "gamma": "gamma", "delta": "delta", "epsilon": "epsilon", "varepsilon": "epsilon",
    "zeta": "zeta", "eta": "eta", "theta": "theta", "vartheta": "theta", "iota": "iota", "kappa": "kappa",
    "lambda": "lambda", "mu": "mu", "nu": "nu", "xi": "xi", "rho": "rho", "sigma": "sigma", "tau": "tau",
    "phi": "phi", "varphi": "phi", "chi": "chi", "psi": "psi", "omega": "omega",
    "Gamma": "capital gamma", "Delta": "delta", "Theta": "capital theta", "Lambda": "capital lambda", "Sigma": "capital sigma",
    "Phi": "capital phi", "Psi": "capital psi", "Omega": "capital omega",
}
_GREEK_UNI = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon", "ζ": "zeta", "η": "eta", "θ": "theta",
    "λ": "lambda", "μ": "mu", "ν": "nu", "ξ": "xi", "ρ": "rho", "σ": "sigma", "τ": "tau", "φ": "phi", "χ": "chi",
    "ψ": "psi", "ω": "omega", "Δ": "delta", "Σ": "capital sigma", "Ω": "capital omega", "Π": "capital pi",
}

_SUPER = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9", "⁻": "-"}
_SUB = {"₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9"}

_FUNCS = {"sin", "cos", "tan", "cot", "sec", "csc", "log", "ln", "exp", "arcsin", "arccos", "arctan", "sinh", "cosh",
          "tanh", "det", "min", "max"}

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def int_to_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    if n < 100:
        return _TENS[n // 10] + ("" if n % 10 == 0 else " " + _ONES[n % 10])
    if n < 1000:
        rest = n % 100
        return _ONES[n // 100] + " hundred" + ("" if rest == 0 else " " + int_to_words(rest))
    return str(n)


# ================================================================= tokenizer
_OP_CMDS = {
    "pm": "±", "mp": "∓", "times": "×", "cdot": "·", "div": "÷", "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥",
    "neq": "≠", "ne": "≠", "approx": "≈", "to": "→", "rightarrow": "→", "infty": "∞", "ldots": "…", "cdots": "…",
    "dots": "…", "lt": "<", "gt": ">",
}
_IGNORED_CMDS = {"left", "right", "big", "Big", "bigg", "Bigg", "displaystyle", "limits", "quad", "qquad", "!", ",", ";", ":", " ",
                 "mathrm", "mathbf", "mathit", "mathcal", "boldsymbol", "operatorname", "bar", "hat", "vec"}
_TOKEN = re.compile(
    r"""
    (?P<text>\\(?:text|textbf|textit|mathrm|operatorname)\{[^{}]*\}) |
    (?P<cmd>\\[A-Za-z]+|\\[^A-Za-z\s]) |
    (?P<num>\d+(?:\.\d+)?)             |
    (?P<word>[A-Za-z]{3,})             |
    (?P<ch>[A-Za-z])                   |
    (?P<uni>[^\s\w]|_|[^\x00-\x7F])  |
    (?P<ws>\s+)
    """,
    re.X,
)


def _tokenize(expr: str) -> list[tuple[str, str]]:
    expr = expr.strip()
    # unicode superscripts/subscripts -> ^ / _
    def sup(m: re.Match) -> str:
        return "^{" + "".join(_SUPER[c] for c in m.group(0)) + "}"

    def sub(m: re.Match) -> str:
        return "_{" + "".join(_SUB[c] for c in m.group(0)) + "}"

    expr = re.sub("[" + "".join(_SUPER) + "]+", sup, expr)
    expr = re.sub("[" + "".join(_SUB) + "]+", sub, expr)
    expr = expr.replace("√", " √ ")

    toks: list[tuple[str, str]] = []
    pos = 0
    while pos < len(expr):
        m = _TOKEN.match(expr, pos)
        if not m:
            pos += 1
            continue
        pos = m.end()
        kind = m.lastgroup or ""
        val = m.group(0)
        if kind == "ws":
            continue
        if kind == "text":
            literal = val[val.index("{") + 1:-1].strip()
            if literal:
                toks.append(("word", literal))
            continue
        if kind == "cmd":
            name = val[1:]
            if name in _IGNORED_CMDS:
                continue
            if name in _OP_CMDS:
                toks.append(("op", _OP_CMDS[name]))
            elif name in _GREEK:
                toks.append(("word", _GREEK[name]))
            elif name == "pi":
                toks.append(("word", "pi"))
            elif name in {"frac", "dfrac", "tfrac", "sqrt", "sum", "prod", "int", "lim", "text", "textbf", "mathrm_"}:
                toks.append(("cmd", name))
            elif name in _FUNCS:
                toks.append(("func", name))
            elif name in {"{", "}"}:
                toks.append(("uni", name))
            elif name == "|":
                toks.append(("uni", "|"))
            else:
                toks.append(("word", name))
        elif kind == "word":
            low = val.lower()
            # split things like "sinx"? keep simple: known function -> func, otherwise a spoken word
            if low in _FUNCS:
                toks.append(("func", low))
            elif low in {"sqrt"}:
                toks.append(("cmd", "sqrt"))
            elif low in {"pi"}:
                toks.append(("word", "pi"))
            else:
                toks.append(("word", val))
        elif kind == "ch":
            toks.append(("id", val))
        elif kind == "num":
            toks.append(("num", val))
        elif kind == "uni":
            if val in _GREEK_UNI:
                toks.append(("word", _GREEK_UNI[val]))
            elif val == "π":
                toks.append(("word", "pi"))
            elif val == "∞":
                toks.append(("op", "∞"))
            elif val == "∑":
                toks.append(("cmd", "sum"))
            elif val == "∏":
                toks.append(("cmd", "prod"))
            elif val == "∫":
                toks.append(("cmd", "int"))
            elif val == "√":
                toks.append(("cmd", "sqrt"))
            elif val == "×":
                toks.append(("op", "×"))
            elif val == "÷":
                toks.append(("op", "÷"))
            elif val == "·" or val == "⋅":
                toks.append(("op", "·"))
            elif val in "≤≥≠≈±∓→":
                toks.append(("op", val))
            elif val in {"$"}:
                continue
            else:
                toks.append(("uni", val))
    return toks


# ==================================================================== parser
ADD_OPS = {"+", "-", "±", "∓", "=", "≠", "<", ">", "≤", "≥", "≈", "→"}
MUL_OPS = {"*", "×", "·", "/", "÷"}


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]):
        self.t = tokens
        self.i = 0

    # ---- helpers
    def peek(self, k: int = 0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else None

    def next(self):
        tok = self.peek()
        self.i += 1
        return tok

    def at(self, kind: str, val: str | None = None, k: int = 0) -> bool:
        tok = self.peek(k)
        return bool(tok) and tok[0] == kind and (val is None or tok[1] == val)

    def at_val(self, vals: set[str]) -> bool:
        tok = self.peek()
        return bool(tok) and tok[1] in vals and tok[0] in {"uni", "op"}

    # ---- grammar
    def parse_seq(self, stop: set[str] | None = None):
        stop = stop or set()
        parts: list = []
        while self.peek() is not None:
            tok = self.peek()
            if tok[0] in {"uni", "op"} and tok[1] in stop:
                break
            if tok[0] in {"uni", "op"} and tok[1] in ADD_OPS:
                parts.append(("op", tok[1]))
                self.next()
                continue
            if tok[0] == "uni" and tok[1] in {",", ";", ".", ":"}:
                parts.append(("pause",))
                self.next()
                continue
            before = self.i
            parts.append(self.parse_term(stop))
            if self.i == before:       # guarantee progress
                self.next()
        return ("seq", parts)

    def parse_term(self, stop: set[str]):
        factors = [("", self.parse_factor())]
        while True:
            tok = self.peek()
            if tok is None:
                break
            if tok[0] in {"uni", "op"} and tok[1] in stop:
                break
            if tok[0] in {"uni", "op"} and tok[1] in MUL_OPS:
                self.next()
                conn = "div" if tok[1] in {"/", "÷"} else "times"
                factors.append((conn, self.parse_factor()))
                continue
            if self._starts_atom(tok):
                factors.append(("imul", self.parse_factor()))
                continue
            break
        return ("term", factors)

    def _starts_atom(self, tok) -> bool:
        kind, val = tok
        if kind in {"num", "id", "word", "func", "cmd"}:
            return True
        return kind == "uni" and val in {"(", "[", "{", "|"} or kind == "op" and val == "∞"

    def parse_factor(self):
        tok = self.peek()
        if tok and tok[0] in {"uni", "op"} and tok[1] in {"-", "+", "±", "∓"}:
            self.next()
            return ("unary", tok[1], self.parse_factor())
        return self.parse_power()

    def parse_power(self):
        base = self.parse_atom()
        while True:
            tok = self.peek()
            if tok is None:
                break
            if tok == ("uni", "^"):
                self.next()
                base = ("pow", base, self.parse_script())
            elif tok == ("uni", "_"):
                self.next()
                base = ("sub", base, self.parse_script())
            elif tok == ("uni", "!"):
                self.next()
                base = ("fact", base)
            elif tok == ("uni", "%"):
                self.next()
                base = ("percent", base)
            else:
                break
        return base

    def parse_script(self):
        tok = self.peek()
        if tok == ("uni", "{"):
            self.next()
            inner = self.parse_seq({"}"})
            if self.peek() == ("uni", "}"):
                self.next()
            return ("brace", inner)
        if tok and tok[0] in {"uni", "op"} and tok[1] in {"-", "+"}:
            self.next()
            return ("unary", tok[1], self.parse_script())
        return self.parse_atom()

    def parse_group(self, close: str):
        inner = self.parse_seq({close})
        if self.peek() and self.peek()[1] == close:
            self.next()
        return inner

    def parse_brace_arg(self):
        """Argument of a LaTeX command: {...} or a single atom."""
        if self.peek() == ("uni", "{"):
            self.next()
            return ("brace", self.parse_group("}"))
        if self.peek() is None:
            return ("seq", [])
        return self.parse_atom()

    def parse_atom(self):
        tok = self.next()
        if tok is None:
            return ("seq", [])
        kind, val = tok
        if kind == "num":
            return ("num", val)
        if kind == "id":
            if val in {"f", "g", "h", "F", "G", "H"} and self.peek() == ("uni", "("):
                self.next()
                return ("call", val, self.parse_group(")"))
            return ("id", val)
        if kind == "word":
            return ("word", val)
        if kind == "op" and val == "∞":
            return ("word", "\u221e")
        if kind == "func":
            arg = None
            nxt = self.peek()
            if nxt is not None and nxt in {("uni", "("), ("uni", "[")}:
                self.next()
                arg = self.parse_group(")" if nxt[1] == "(" else "]")
            elif nxt is not None and self._starts_atom(nxt):
                arg = self.parse_power()
            return ("func", val, arg)
        if kind == "uni":
            if val in {"(", "["}:
                return ("group", self.parse_group(")" if val == "(" else "]"))
            if val == "{":
                return ("brace", self.parse_group("}"))
            if val == "|":
                inner = self.parse_seq({"|"})
                if self.peek() == ("uni", "|"):
                    self.next()
                return ("abs", inner)
            return ("seq", [])
        if kind == "cmd":
            return self.parse_command(val)
        return ("seq", [])

    def parse_command(self, name: str):
        if name in {"frac", "dfrac", "tfrac"}:
            a = self.parse_brace_arg()
            b = self.parse_brace_arg()
            return ("frac", a, b)
        if name == "sqrt":
            index = None
            if self.peek() == ("uni", "["):
                self.next()
                index = self.parse_group("]")
            return ("sqrt", index, self.parse_brace_arg())
        if name in {"text", "textbf"}:
            if self.peek() == ("uni", "{"):
                self.next()
                words = []
                while self.peek() and self.peek() != ("uni", "}"):
                    words.append(self.next()[1])
                if self.peek():
                    self.next()
                return ("word", " ".join(words))
            return ("seq", [])
        if name in {"sum", "prod", "int", "lim"}:
            lower = upper = None
            for _ in range(2):
                if self.peek() == ("uni", "_") and lower is None:
                    self.next()
                    lower = self.parse_script()
                elif self.peek() == ("uni", "^") and upper is None:
                    self.next()
                    upper = self.parse_script()
            body = None
            if self.peek() is not None and self._starts_atom(self.peek()):
                body = self.parse_term(set())
            return ("bigop", name, lower, upper, body)
        return ("seq", [])


# ================================================================== speaker
def _simple_num(node):
    """Unwrap {2}, seq[term[num]] wrappers and return the number string if it is a plain number."""
    while node:
        k = node[0]
        if k == "num":
            return node[1]
        if k == "brace":
            node = node[1]
        elif k == "seq" and len(node[1]) == 1:
            node = node[1][0]
        elif k == "term" and len(node[1]) == 1:
            node = node[1][0][1]
        else:
            return None
    return None


class _Speaker:
    def __init__(self, lang: str):
        self.w = WORDS.get(lang, WORDS["en"])
        self.lang = lang if lang in WORDS else "en"

    def num(self, s: str) -> str:
        if self.lang != "en":
            return s
        if "." in s:
            whole, frac = s.split(".", 1)
            return f"{self.num(whole)} {self.w['point']} " + " ".join(_ONES[int(d)] for d in frac)
        return int_to_words(int(s))

    def say(self, n, ctx: str = "") -> str:
        if not n:
            return ""
        k = n[0]
        w = self.w
        if k == "seq":
            return self.say_seq(n[1])
        if k == "term":
            return self.say_term(n[1])
        if k == "num":
            return self.num(n[1])
        if k == "id":
            return n[1]
        if k == "word":
            return n[1] if n[1] != "pi" else w["pi"]
        if k == "brace":
            return self.say(n[1])
        if k == "group":
            inner = self.say(n[1])
            return f"{w['quantity']} {inner}" if ctx == "base" else inner
        if k == "abs":
            return f"{w['abs']} {self.say(n[1])}"
        if k == "unary":
            word = {"-": w["neg"], "+": w["pos"], "±": w["pm"], "∓": w["mp"]}[n[1]]
            return f"{word} {self.say(n[2])}"
        if k == "pow":
            return self.say_pow(n)
        if k == "sub":
            return f"{self.say(n[1])} {w['sub']} {self.say(n[2])}"
        if k == "fact":
            return f"{self.say(n[1], 'base')} {w['fact']}"
        if k == "percent":
            return f"{self.say(n[1])} {w['percent']}"
        if k == "call":
            return f"{n[1]} {w['of']} {self.say(n[2])}"
        if k == "func":
            name = w.get(n[1], n[1])
            return f"{name} {w['of']} {self.say(n[2])}" if n[2] else name
        if k == "frac":
            a, b = self.say(n[1]), self.say(n[2])
            comma = "," if len(a.split()) > 2 else ""
            return f"{a}{comma} {w['div']} {b}"
        if k == "sqrt":
            inner = self.say(n[2])
            if n[1] is not None:
                idx = self.say(n[1])
                if idx == self.num("3"):
                    return f"{w['cbrt']} {inner}"
                return f"{idx} {w['root']} {w['of']} {inner}" if self.lang == "en" else f"{idx} {w['root']} {inner}"
            return f"{w['sqrt']} {inner}"
        if k == "bigop":
            return self.say_bigop(n)
        return ""

    def say_pow(self, n) -> str:
        w = self.w
        base = self.say(n[1], "base")
        exp = n[2]
        exp_txt = self.say(exp)
        simple = _simple_num(exp)
        if n[1][0] == "func" and n[1][2] is not None and simple in {"2", "3"}:
            f = n[1]
            word = w["squared"] if simple == "2" else w["cubed"]
            return f"{w.get(f[1], f[1])} {word} {w['of']} {self.say(f[2])}"
        if simple == "2":
            return f"{base} {w['squared']}"
        if simple == "3":
            return f"{base} {w['cubed']}"
        if exp[0] == "unary" and exp[1] == "-" and _simple_num(exp[2]) == "1":
            return f"{base} {w['inverse']}" if self.lang != "en" else f"{base} to the power of {w['neg']} {self.num('1')}"
        return f"{base} {w['power']} {exp_txt}"

    def say_bigop(self, n) -> str:
        w = self.w
        _, name, lower, upper, body = n
        head = {"sum": w["sum"], "prod": w["prod"], "int": w["int"], "lim": w["lim"]}[name]
        bits = [head]
        if name == "lim" and lower is not None:
            low = self.say(lower).replace(f" {self.say_op('→')} ", f" {w['approaches']} ")
            bits.append(f"{w['as']} {low}")
        else:
            if lower is not None:
                bits.append(f"{w['from']} {self.say(lower)}")
            if upper is not None:
                bits.append(f"{w['to']} {self.say(upper)}")
        bits.append(w["of"])
        if body is not None:
            bits.append(self.say(body))
        return " ".join(b for b in bits if b)

    def say_op(self, op: str) -> str:
        w = self.w
        return {
            "+": w["plus"], "-": w["minus"], "±": w["pm"], "∓": w["mp"], "=": w["eq"], "≠": w["ne"], "<": w["lt"],
            ">": w["gt"], "≤": w["le"], "≥": w["ge"], "≈": w["approx"], "→": "goes to",
        }.get(op, op)

    def say_seq(self, parts: list) -> str:
        out: list[str] = []
        prev_term = False
        for p in parts:
            if p[0] == "op":
                op = p[1]
                if op == "→":
                    out.append(self.w["approaches"])
                    prev_term = False
                    continue
                if not prev_term and op in {"-", "+", "±", "∓"}:
                    out.append({"-": self.w["neg"], "+": self.w["pos"], "±": self.w["pm"], "∓": self.w["mp"]}[op])
                else:
                    out.append(self.say_op(op))
                prev_term = False
            elif p[0] == "pause":
                if out:
                    out[-1] = out[-1] + ","
                prev_term = False
            else:
                out.append(self.say(p))
                prev_term = True
        return " ".join(x for x in out if x)

    def say_term(self, factors: list) -> str:
        pieces: list[str] = []
        prev = None
        for idx, (conn, f) in enumerate(factors):
            next_conn = factors[idx + 1][0] if idx + 1 < len(factors) else None
            ctx = "base" if (f[0] == "group" and (conn == "imul" or next_conn == "imul")) else ""
            txt = self.say(f, ctx)
            if conn == "imul" and prev is not None and prev[0] == "group" and f[0] == "group":
                txt = f"{self.w['times']} {txt}"
            prev = f
            if conn == "div":
                left = " ".join(pieces)
                comma = "," if len(left.split()) > 2 else ""
                if pieces:
                    pieces[-1] = pieces[-1] + comma
                right = txt
                if f[0] == "group" and len(f[1][1]) > 1:
                    right = f"{self.w['quantity']} {txt}"
                pieces.append(f"{self.w['div']} {right}")
            elif conn == "times":
                pieces.append(f"{self.w['times']} {txt}")
            else:
                pieces.append(txt)
        return " ".join(p for p in pieces if p)


# ================================================================= public API
def math_to_speech(expr: str, lang: str = "en") -> str:
    """Verbalize LaTeX or plain/Unicode math for a TTS engine."""
    expr = (expr or "").strip()
    expr = re.sub(r"^\$\$|\$\$$|^\$|\$$", "", expr).strip()
    expr = re.sub(r"^\\\(|\\\)$|^\\\[|\\\]$", "", expr).strip()
    if not expr:
        return ""
    lang = lang.split("-")[0] if lang else "en"
    parser = _Parser(_tokenize(expr))
    tree = parser.parse_seq()
    text = _Speaker(lang).say(tree)
    return re.sub(r"\s+,", ",", re.sub(r"\s+", " ", text)).strip()


# ---------------------------------------------------------------- code speech
_DEF_PATTERNS = [
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)", re.M),
    re.compile(r"^\s*class\s+([A-Za-z_]\w*)", re.M),
    re.compile(r"\bfunction\s+([A-Za-z_$][\w$]*)", re.M),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>", re.M),
    re.compile(r"^\s*(?:public|private|protected|static|\s)*[\w<>\[\]]+\s+([A-Za-z_]\w*)\s*\([^)]*\)\s*\{", re.M),
]
_LANG_NAMES = {"python": "Python", "javascript": "JavaScript", "typescript": "TypeScript", "html": "HTML", "css": "CSS",
               "cpp": "C plus plus", "c": "C", "java": "Java", "bash": "shell", "sql": "SQL", "json": "JSON", "go": "Go",
               "rust": "Rust", "csharp": "C sharp", "kotlin": "Kotlin", "php": "PHP", "jsx": "React", "tsx": "React"}


def _defined_names(code: str) -> list[str]:
    names: list[str] = []
    for pat in _DEF_PATTERNS:
        for m in pat.finditer(code):
            n = m.group(1)
            if n not in names and n not in {"if", "for", "while", "switch", "return", "catch"}:
                names.append(n)
    return names


def code_summary_speech(segment: Segment, lang: str = "en", on_screen: bool = True) -> str:
    """A short spoken description instead of reading code symbol by symbol."""
    language = _LANG_NAMES.get((segment.language or "").lower(), (segment.language or "").capitalize() or "the")
    names = _defined_names(segment.content)[:5]
    lines = len([l for l in segment.content.split("\n") if l.strip()])
    fname = segment.filename or ""
    where = f" in {fname}" if fname else ""

    if lang == "gu":
        where = f" {fname} માં" if fname else ""
        base = f"મેં {language} કોડ તૈયાર કર્યો છે{where}."
        if names:
            base += " તેમાં " + ", ".join(names) + " છે."
        return base + (" પૂરો કોડ સ્ક્રીન પર બતાવ્યો છે." if on_screen else "")
    if lang == "hi":
        where = f" {fname} में" if fname else ""
        base = f"मैंने {language} कोड तैयार किया है{where}."
        if names:
            base += " इसमें " + ", ".join(names) + " हैं।"
        return base + (" पूरा कोड स्क्रीन पर दिखाया गया है।" if on_screen else "")

    base = f"I created the {language} code{where}, {lines} lines."
    if names:
        base = f"I created the {language} code{where} with " + _join_names(names) + "."
    return base + (" The complete code is displayed on screen." if on_screen else "")


def _join_names(names: list[str]) -> str:
    spoken = [n.replace("_", " ") for n in names]
    if len(spoken) == 1:
        return spoken[0]
    return ", ".join(spoken[:-1]) + " and " + spoken[-1]


_CODE_SYMBOLS = {
    "==": " equals equals ", "!=": " not equals ", "<=": " less than or equal to ", ">=": " greater than or equal to ",
    "=>": " arrow ", "->": " arrow ", "&&": " and ", "||": " or ", "++": " plus plus ", "--": " minus minus ",
    "+=": " plus equals ", "-=": " minus equals ", "*=": " times equals ", "/=": " divided equals ", "::": " double colon ",
    "(": " open parenthesis ", ")": " close parenthesis ", "{": " open brace ", "}": " close brace ",
    "[": " open bracket ", "]": " close bracket ", ":": " colon ", ";": " semicolon ", ",": " comma ", ".": " dot ",
    "=": " equals ", "+": " plus ", "-": " minus ", "*": " star ", "/": " slash ", "%": " modulo ", "<": " less than ",
    ">": " greater than ", "!": " not ", "_": " underscore ", "\"": " quote ", "'": " quote ", "#": " hash ",
    "@": " at ", "$": " dollar ", "&": " ampersand ", "|": " pipe ", "\\": " backslash ", "?": " question mark ",
}
_SYMBOL_RE = re.compile("|".join(re.escape(k) for k in sorted(_CODE_SYMBOLS, key=len, reverse=True)))


def code_to_speech(code: str, max_lines: int = 40) -> str:
    """Verbatim spoken form. Only used when the user explicitly asks to have code read aloud."""
    lines = code.split("\n")
    out: list[str] = []
    shown = 0
    for idx, line in enumerate(lines, 1):
        if not line.strip():
            continue
        if shown >= max_lines:
            out.append(f"and {len([l for l in lines[idx-1:] if l.strip()])} more lines.")
            break
        indent = len(line) - len(line.lstrip(" \t"))
        level = indent // 4 if "\t" not in line[:indent] else line[:indent].count("\t")
        spoken = _SYMBOL_RE.sub(lambda m: _CODE_SYMBOLS[m.group(0)], line.strip())
        spoken = re.sub(r"\s+", " ", spoken).strip()
        prefix = f"line {int(shown) + 1}"
        if level:
            prefix += f", indent {int_to_words(level)}"
        out.append(f"{prefix}: {spoken}.")
        shown += 1
    return " ".join(out)


# ----------------------------------------------------------------- prose speech
_URL = re.compile(r"https?://\S+")


def text_to_speech(text: str, lang: str = "en", limit: int = 700) -> str:
    """Strip markdown so the voice does not read symbols; keep it short."""
    t = text or ""
    t = re.sub(r"```.*?```", " ", t, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = _URL.sub("link" if lang == "en" else "", t)
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"(\*\*|__|\*|_)(.+?)\1", r"\2", t)
    t = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+(.*?)\s*$", lambda m: m.group(1) if re.search(r"[.!?।:]$", m.group(1)) else m.group(1) + ".", t, flags=re.M)
    t = re.sub(r"\|", " ", t)
    t = re.sub(r"\$\$?([^$]+)\$\$?", lambda m: math_to_speech(m.group(1), lang), t)
    t = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > limit:
        cut = t[:limit]
        m = list(re.finditer(r"[.!?।]\s", cut))
        t = (cut[: m[-1].end()] if m else cut).strip()
    return t
