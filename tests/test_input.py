from app.input.normalizer import normalize


def test_original_is_preserved():
    n = normalize("  Hello   world  ")
    assert n.original_text == "  Hello   world  "
    assert n.text == "Hello world"


def test_romanized_gujarati_is_conversation_not_error():
    n = normalize("mare ghare javu che")
    assert n.language == "gu" and n.romanized
    assert n.intent_hint == "conversation"
    assert not n.needs_clarification


def test_gujarati_script():
    n = normalize("મારે ઘરે જવું છે")
    assert n.language == "gu" and not n.romanized and n.script == "gujarati"
    assert n.intent_hint == "conversation"


def test_detects_code_and_math():
    assert normalize("def add(a,b):\n    return a+b\nprint(add(1,2))").has_code
    assert normalize("solve x^2 - 5x + 6 = 0").has_math
    assert normalize("x = (-b ± √(b² - 4ac)) / 2a").has_math
    assert not normalize("Create a Python calculator").has_code


def test_incomplete_and_empty():
    assert normalize("I want to build a website and").needs_clarification
    assert normalize("   ").needs_clarification


def test_references_and_followups():
    assert normalize("Add login to it").has_reference
    assert normalize("એમાં login ઉમેરો").has_reference
    assert normalize("Make the button blue.").followup_style
    assert normalize("read the code aloud").read_aloud


def test_greeting_is_not_a_question():
    n = normalize("kem cho")
    assert n.intent_hint == "conversation" and not n.is_question
