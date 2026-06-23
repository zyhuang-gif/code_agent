`Account.withdraw` is producing the wrong balances. The symptom appears in the account tests, but the root cause may be in another module; trace the call chain before patching.

Fix the shared fee calculation so withdrawals subtract `amount + amount * fee_rate`. Keep `Account.withdraw` using the shared fee function.

Run `python -m pytest -q` from the repository root when you are done.
