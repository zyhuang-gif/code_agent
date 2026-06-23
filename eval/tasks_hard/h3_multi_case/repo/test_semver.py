from semver import parse


def test_parse_full_version():
    assert parse("1.2.3") == (1, 2, 3)


def test_parse_short_version_defaults_patch_to_zero():
    assert parse("1.2") == (1, 2, 0)


def test_parse_prerelease_ignores_suffix():
    assert parse("1.2.3-rc1") == (1, 2, 3)


def test_parse_two_digit_major_short_version():
    assert parse("10.0") == (10, 0, 0)
