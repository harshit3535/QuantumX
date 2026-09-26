from app.models import Segment
from app.response.parser import markdown_to_segments
from app.response.verbalizer import code_summary_speech, code_to_speech, math_to_speech, text_to_speech


def test_quadratic_unicode_and_latex_sound_the_same():
    want = "x equals negative b plus or minus the square root of b squared minus four a c, divided by two a"
    assert math_to_speech("x = (-b ± √(b² - 4ac)) / 2a") == want
    assert math_to_speech(r"x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}") == want


def test_more_math():
    assert math_to_speech("E = mc²") == "E equals m c squared"
    assert math_to_speech(r"\sum_{i=1}^{n} i^2") == "the sum from i equals one to n of i squared"
    assert math_to_speech("a / (b + c)") == "a divided by the quantity b plus c"
    assert math_to_speech("f(x) = x^{n+1}") == "f of x equals x to the power of n plus one"
    assert "cube root" in math_to_speech(r"\sqrt[3]{27}")


def test_math_in_gujarati_words():
    assert "બરાબર" in math_to_speech("x = 5", "gu")


def test_code_is_summarized_not_read():
    seg = Segment(type="code", language="python", filename="calc.py", content="def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b")
    s = code_summary_speech(seg)
    assert "def" not in s and "add" in s and "on screen" in s


def test_code_read_aloud_verbatim():
    s = code_to_speech("def add(a, b):\n    return a + b")
    assert "open parenthesis" in s and "indent one" in s


def test_text_to_speech_strips_markdown():
    s = text_to_speech("## Hi\nSee **this** `x` https://a.b/c")
    assert "*" not in s and "#" not in s and "http" not in s


def test_parser_keeps_code_and_math_separate():
    segs = markdown_to_segments("Intro\n\n$$x^2$$\n\n```python calc.py\ndef f():\n    return 1\n```\n")
    kinds = [s.type for s in segs]
    assert kinds == ["text", "math", "code"]
    code = segs[2]
    assert code.language == "python" and code.filename == "calc.py" and code.content == "def f():\n    return 1"


def test_parser_table_and_list():
    segs = markdown_to_segments("| a | b |\n|---|---|\n| 1 | 2 |\n\n- x\n- y")
    assert segs[0].type == "table" and segs[0].rows == [["1", "2"]]
    assert segs[1].type == "list" and segs[1].items == ["x", "y"]


def test_text_words_and_products_of_groups():
    assert math_to_speech(r"x = 2 \text{ or } x = 3") == "x equals two or x equals three"
    assert math_to_speech(r"\left(x - 3\right) \left(x - 2\right) = 0") == "the quantity x minus three times the quantity x minus two equals zero"
    assert math_to_speech("2(x + 1)") == "two the quantity x plus one"
