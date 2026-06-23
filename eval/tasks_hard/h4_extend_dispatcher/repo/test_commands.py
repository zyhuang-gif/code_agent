import pytest

from commands import dispatch, registered_commands


def test_existing_upper_command_still_works():
    assert dispatch("upper", "Abc") == "ABC"


def test_existing_lower_command_still_works():
    assert dispatch("lower", "Abc") == "abc"


def test_reverse_command_is_registered_and_reverses_text():
    assert "reverse" in registered_commands()
    assert dispatch("reverse", "abc") == "cba"
    assert dispatch("reverse", "stressed") == "desserts"


def test_unknown_command_still_reports_value_error():
    with pytest.raises(ValueError, match="unknown command"):
        dispatch("title", "hello")
