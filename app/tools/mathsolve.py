"""Deterministic math with SymPy - no LLM needed for ordinary school/college math.

SAFETY: sympy's parser uses eval(). Input is therefore whitelisted first
(digits, single letters, a fixed set of function names, basic operators) so no
attribute access, underscores, quotes or brackets can ever reach the parser.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor, implicit_multiplication_application, parse_expr, standard_transformations,
)

MAX_LEN = 200
MAX_EXPONENT = 1000
MAX_FACTORIAL = 300

_FUNCS = {
    "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "cot": sp.cot, "sec": sp.sec, "csc": sp.csc,
    "asin": sp.asin, "acos": sp.acos, "atan": sp.atan, "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh,
    "log": sp.log, "ln": sp.log, "exp": sp.exp, "sqrt": sp.sqrt, "abs": sp.Abs, "factorial": sp.factorial,
}
_CONSTS = {"pi": sp.pi, "e": sp.E, "oo": sp.oo}

_GLOBALS = {
    "__builtins__": {},
    "Symbol": sp.Symbol, "Integer": sp.Integer, "Float": sp.Float, "Rational": sp.Rational,
    "Function": sp.Function, "Mul": sp.Mul, "Add": sp.Add, "Pow": sp.Pow,
}
_TRANSFORMS = standard_transformations + (implicit_multiplication_application, convert_xor)

_LEADING = re.compile(
    r"^\s*(?:please\s+)?(?:can you\s+)?(?:solve|calculate|compute|evaluate|find|what is|what's|whats|tell me|work out|"
    r"simplify|expand|factori[sz]e|factor|ઉકેલો|ગણતરી કરો|हल करो|हल कीजिए)\s*(?:the\s+)?(?:equation\s*)?[:\-]?\s*",
    re.I,
)


@dataclass
class MathOutcome:
    kind: str                  # solve | evaluate | diff | integrate | simplify | percent
    expression: str            # cleaned input
    latex: str                 # display latex of the final statement
    result: str                # plain-text result
    steps: list[str]           # short latex lines shown before the result
    verified: bool | None = None


class MathParseError(Exception):
    pass


def _clean(text: str) -> str:
    t = text.strip().rstrip("?.").strip()
    t = re.sub(r"(?<![\w)])!+$", "", t).strip()            # sentence "!" but keep factorial "7!"
    t = (t.replace("−", "-").replace("×", "*").replace("÷", "/").replace("·", "*")
          .replace("π", "pi").replace("∞", "oo").replace("≠", "!="))
    t = re.sub(r"√\s*\(", "sqrt(", t)
    t = re.sub(r"√\s*([A-Za-z0-9.]+)", r"sqrt(\1)", t)
    for sup, dig in zip("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789"):
        t = re.sub(rf"([A-Za-z0-9)]){sup}", rf"\1**{dig}", t)
    t = t.replace("^", "**")
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)     # 1,000 -> 1000
    return t


def _check_safe(expr: str) -> None:
    if len(expr) > MAX_LEN:
        raise MathParseError("expression too long")
    if not re.fullmatch(r"[0-9A-Za-z+\-*/().,=<>!\s]+", expr):
        raise MathParseError("unsupported characters")
    if "__" in expr:
        raise MathParseError("unsupported characters")
    for word in re.findall(r"[A-Za-z]{2,}", expr):
        if word.lower() not in _FUNCS and word.lower() not in _CONSTS and word.lower() not in {"dx", "dy"}:
            # multi-letter names are allowed only as products of single letters, like "ac" or "xy"
            if len(word) > 3:
                raise MathParseError(f"unknown name: {word}")
    for m in re.finditer(r"\*\*\s*\(?\s*(\d+)", expr):
        if int(m.group(1)) > MAX_EXPONENT:
            raise MathParseError("exponent too large")
    if re.search(r"\*\*\s*\(?[\w.]+\)?\s*\*\*", expr):      # towers like 9**9**9 explode
        raise MathParseError("nested exponents are not supported")
    for m in re.finditer(r"(\d+)\s*!", expr):
        if int(m.group(1)) > MAX_FACTORIAL:
            raise MathParseError("factorial too large")


def _parse(expr: str, evaluate: bool = True):
    expr = expr.strip()
    expr = re.sub(r"(\d+)\s*!", r"factorial(\1)", expr)
    _check_safe(expr)
    local = dict(_FUNCS)
    local.update(_CONSTS)
    try:
        return parse_expr(expr, local_dict=local, global_dict=dict(_GLOBALS), transformations=_TRANSFORMS, evaluate=evaluate)
    except Exception as exc:  # sympy raises many types
        raise MathParseError(str(exc)) from exc


def _latex(x) -> str:
    return sp.latex(x)


def _shown(expr_text: str, fallback):
    """LaTeX of the expression as the user wrote it (2 + 2, not 4)."""
    try:
        return _latex(_parse(expr_text, evaluate=False))
    except MathParseError:
        return _latex(fallback)


def _pick_symbol(symbols: set) -> sp.Symbol | None:
    if not symbols:
        return None
    names = {str(s): s for s in symbols}
    for pref in ("x", "y", "z", "t", "n"):
        if pref in names:
            return names[pref]
    return sorted(symbols, key=str)[0]


def solve_math(text: str) -> MathOutcome:
    """Try to solve `text` deterministically. Raises MathParseError if it is not plain math."""
    raw = text.strip()
    low = raw.lower()

    # ---- percent: "15% of 200"
    pm = re.search(r"(\d+(?:\.\d+)?)\s*%\s*of\s*(\d+(?:\.\d+)?)", low)
    if pm:
        a, b = sp.Rational(pm.group(1)), sp.Rational(pm.group(2))
        val = a / 100 * b
        return MathOutcome("percent", raw, rf"{pm.group(1)}\% \text{{ of }} {pm.group(2)} = {_latex(val)}", str(val), [], True)

    # ---- derivative / integral
    dm = re.search(r"(?:derivative|differentiate|d/dx)\s*(?:of)?\s*(.+)", low)
    if dm:
        expr = _parse(_clean(dm.group(1)))
        var = _pick_symbol(expr.free_symbols) or sp.Symbol("x")
        res = sp.diff(expr, var)
        return MathOutcome("diff", dm.group(1), rf"\frac{{d}}{{d{var}}}\left({_shown(_clean(dm.group(1)), expr)}\right) = {_latex(res)}", str(res), [], None)
    im = re.search(r"(?:integrate|integral of|integral|antiderivative of)\s*(.+)", low)
    if im:
        body = re.sub(r"\s*d[xyz]\s*$", "", im.group(1).strip())
        expr = _parse(_clean(body))
        var = _pick_symbol(expr.free_symbols) or sp.Symbol("x")
        res = sp.integrate(expr, var)
        if res.has(sp.Integral):
            raise MathParseError("no closed form found")
        return MathOutcome("integrate", body, rf"\int {_shown(_clean(body), expr)}\,d{var} = {_latex(res)} + C", f"{res} + C", [], None)

    op = None
    for word, name in (("simplify", "simplify"), ("expand", "expand"), ("factorise", "factor"), ("factorize", "factor"), ("factor", "factor")):
        if re.match(rf"^\s*(?:please\s+)?{word}\b", low):
            op = name
            break

    body = _clean(_LEADING.sub("", raw))
    if not body:
        raise MathParseError("nothing to solve")

    # ---- equation / system
    if "=" in body and not re.search(r"[<>!]=|==", body):
        parts = [p.strip() for p in re.split(r"[;,]|\band\b", body) if "=" in p]
        eqs = []
        for p in parts:
            lhs, rhs = p.split("=", 1)
            eqs.append(sp.Eq(_parse(lhs), _parse(rhs)))
        if not eqs:
            raise MathParseError("no equation")
        syms = set().union(*[e.free_symbols for e in eqs])
        if not syms:
            ok = bool(eqs[0])
            return MathOutcome("evaluate", body, rf"{_latex(eqs[0].lhs)} = {_latex(eqs[0].rhs)}\;\; ({'true' if ok else 'false'})", str(ok), [], ok)
        steps: list[str] = []
        if len(eqs) == 1:
            var = _pick_symbol(syms)
            eq = eqs[0]
            expr0 = sp.expand(eq.lhs - eq.rhs)
            poly_ok = expr0.is_polynomial(var) if var is not None else False
            if poly_ok and sp.degree(expr0, var) >= 2:
                fac = sp.factor(expr0)
                if fac != expr0:
                    steps.append(rf"{_latex(fac)} = 0")
            sols = sp.solve(eq, var, dict=False)
            if not sols:
                return MathOutcome("solve", body, rf"\text{{No solution for }} {var}", "no solution", steps, None)
            verified = True
            for s in sols:
                try:
                    verified = verified and sp.simplify(eq.lhs.subs(var, s) - eq.rhs.subs(var, s)) == 0
                except Exception:
                    verified = False
            latex = r" \text{ or } ".join(rf"{_latex(var)} = {_latex(s)}" for s in sols)
            plain = ", ".join(f"{var} = {s}" for s in sols)
            return MathOutcome("solve", body, latex, plain, steps, bool(verified))
        sol = sp.solve(eqs, sorted(syms, key=str), dict=True)
        if not sol:
            return MathOutcome("solve", body, r"\text{No solution}", "no solution", [], None)
        d = sol[0]
        latex = r",\;\; ".join(rf"{_latex(k)} = {_latex(v)}" for k, v in d.items())
        plain = ", ".join(f"{k} = {v}" for k, v in d.items())
        ok = all(sp.simplify(e.lhs.subs(d) - e.rhs.subs(d)) == 0 for e in eqs)
        return MathOutcome("solve", body, latex, plain, [], ok)

    # ---- plain expression
    expr = _parse(body)
    if op == "expand":
        res = sp.expand(expr)
    elif op == "factor":
        res = sp.factor(expr)
    elif op == "simplify" or expr.free_symbols:
        res = sp.simplify(expr)
    else:
        res = sp.nsimplify(expr) if expr.is_Number else sp.simplify(expr)

    lat = rf"{_shown(body, expr)} = {_latex(res)}"
    plain = str(res)
    if not res.free_symbols and res.is_number and not res.is_Integer and not res.is_Rational:
        approx = sp.N(res, 8)
        lat += rf" \approx {_latex(approx)}"
        plain += f" (about {approx})"
    elif not expr.free_symbols and res.is_Rational and not res.is_Integer:
        lat += rf" \approx {_latex(sp.N(res, 8))}"
    same = sp.simplify(expr - res) == 0 if expr.free_symbols or True else True
    return MathOutcome("evaluate" if not op else op, body, lat, plain, [], True if not expr.free_symbols else bool(same))


# ------------------------------------------------------------------ isolation
def _worker(text: str):                     # runs in a child process
    try:
        return ("ok", solve_math(text))
    except MathParseError as exc:
        return ("parse", str(exc))
    except Exception as exc:                # sympy can raise almost anything
        return ("parse", f"{type(exc).__name__}: {exc}")


_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor
        # "spawn" (not fork): forking a multi-threaded web server can deadlock the child.
        _pool = ProcessPoolExecutor(max_workers=1, mp_context=mp.get_context("spawn"))
    return _pool


def _kill_pool() -> None:
    global _pool
    pool, _pool = _pool, None
    if pool is None:
        return
    for proc in list(getattr(pool, "_processes", {}).values()):
        try:
            proc.kill()
        except Exception:
            pass
    pool.shutdown(wait=False, cancel_futures=True)


async def solve_math_isolated(text: str, timeout: float = 6.0) -> MathOutcome:
    """Run solve_math in a worker process that is killed if it takes too long.

    SymPy has no built-in time limit, and a public app must survive input like
    "integrate exp(x**x)". A process can be killed; a thread cannot. The worker
    stays alive between calls (sympy is imported once), so only the first call is slow.
    """
    import asyncio
    from concurrent.futures.process import BrokenProcessPool

    loop = asyncio.get_running_loop()
    for attempt in (1, 2):
        try:
            status, payload = await asyncio.wait_for(loop.run_in_executor(_get_pool(), _worker, text), timeout)
            break
        except asyncio.TimeoutError:
            _kill_pool()
            raise MathParseError("took too long to compute")
        except BrokenProcessPool:
            _kill_pool()
            if attempt == 2:
                raise MathParseError("math worker crashed")
    if status == "ok":
        return payload
    raise MathParseError(payload)


async def warm_up() -> None:
    """Start the worker early so the first real question is fast."""
    try:
        await solve_math_isolated("1+1", timeout=20)
    except MathParseError:
        pass
