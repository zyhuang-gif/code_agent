from __future__ import annotations


def calculate_fee(amount: float, rate: float) -> float:
    if amount < 0:
        raise ValueError("amount must be non-negative")
    if rate < 0:
        raise ValueError("rate must be non-negative")
    return amount + rate


