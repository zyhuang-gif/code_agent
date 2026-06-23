The geometry package has failing area tests. Please fix the active implementation used by `from geometry import Circle, Rectangle`.

There is a legacy module with similar code, but it is not part of the public import path. Read the package wiring before editing so you fix the implementation that the tests actually exercise.

Run `python -m pytest -q` from the repository root when you are done.
