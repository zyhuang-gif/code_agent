from __future__ import annotations

from dataclasses import dataclass

import fees


@dataclass
class Account:
    owner: str
    balance: float
    fee_rate: float = 0.02

    def withdraw(self, amount: float) -> None:
        if amount <= 0:
            raise ValueError("amount must be positive")
        debit = amount + fees.calculate_fee(amount, self.fee_rate)
        if debit > self.balance:
            raise ValueError("insufficient funds")
        self.balance -= debit
