from normalizer import normalize_name
from usernames import make_username


def test_make_username_normalizes_across_modules():
    assert make_username(" Ada ", "LOVELACE") == "ada.lovelace"


def test_normalize_name_replaces_internal_spaces():
    assert normalize_name(" Grace Hopper ") == "grace-hopper"
