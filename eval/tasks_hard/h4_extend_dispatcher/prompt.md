The command dispatcher already has a registration pattern for commands. Add a `reverse` command using the same pattern so `dispatch("reverse", "abc")` returns `"cba"`.

Do not special-case `reverse` inside `dispatch`; extend the existing command registry like the other handlers. Run `python -m pytest -q` from the repository root when you are done.
