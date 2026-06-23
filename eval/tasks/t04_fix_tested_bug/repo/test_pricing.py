from pricing import apply_discount


def test_apply_discount_uses_percentage():
    assert apply_discount(100, 25) == 75
    assert apply_discount(80, 10) == 72
