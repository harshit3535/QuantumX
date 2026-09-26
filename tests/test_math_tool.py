import asyncio

import pytest

from app.tools.mathsolve import MathParseError, solve_math, solve_math_isolated


def test_quadratic_verified():
    r = solve_math("solve x^2 - 5x + 6 = 0")
    assert r.result == "x = 2, x = 3" and r.verified


def test_system_and_calculus():
    assert "x = 2" in solve_math("x + y = 3, x - y = 1").result
    assert solve_math("derivative of x^3 + 2x").result == "3*x**2 + 2"


def test_percent_and_factorial():
    assert solve_math("what is 15% of 200").result == "30"
    assert solve_math("what is 7!").result == "5040"


@pytest.mark.parametrize("bad", [
    "__import__('os').system('ls')", "solve x = open('f')", "9**9**9**9", "2^1000000", "hello there", "what is the capital of france",
])
def test_unsafe_or_not_math_is_rejected(bad):
    with pytest.raises(MathParseError):
        solve_math(bad)


def test_no_closed_form_falls_through():
    with pytest.raises(MathParseError):
        solve_math("integrate exp(x**x)")


def test_isolated_runs():
    assert asyncio.run(solve_math_isolated("2+2")).result == "4"


def test_timeout_kills_worker_and_pool_recovers():
    from app.tools import mathsolve
    mathsolve._kill_pool()                        # cold start

    async def go():
        # a 10 ms budget cannot even start the worker -> must raise, not hang
        with pytest.raises(MathParseError):
            await solve_math_isolated("2+2", timeout=0.01)
        return await solve_math_isolated("3+4", timeout=30)      # fresh worker works again
    assert asyncio.run(go()).result == "7"
