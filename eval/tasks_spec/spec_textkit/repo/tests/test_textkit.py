import textkit


def test_slugify_basic():
    assert textkit.slugify("  Hello  World ") == "hello-world"


def test_truncate_basic():
    assert textkit.truncate("hello", 3) == "hel…"
    assert textkit.truncate("hi", 5) == "hi"


def test_parse_bool_basic():
    assert textkit.parse_bool(" TRUE ") is True
    assert textkit.parse_bool("no") is False