import fees
from account import Account


def test_withdraw_subtracts_amount_plus_percentage_fee_for_small_purchase():
    account = Account("Ada", 100.0, fee_rate=0.05)

    account.withdraw(20.0)

    assert account.balance == 79.0


def test_withdraw_subtracts_amount_plus_percentage_fee_for_larger_purchase():
    account = Account("Grace", 250.0, fee_rate=0.125)

    account.withdraw(80.0)

    assert account.balance == 160.0


def test_withdraw_continues_to_use_shared_fee_calculator(monkeypatch):
    account = Account("Lin", 50.0, fee_rate=0.5)
    monkeypatch.setattr(fees, "calculate_fee", lambda amount, rate: 3.0)

    account.withdraw(10.0)

    assert account.balance == 37.0
