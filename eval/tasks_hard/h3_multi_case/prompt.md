The semver parser only handles one happy path. Extend `parse(version)` so it returns `(major, minor, patch)` for all supported inputs:

- `"1.2.3" -> (1, 2, 3)`
- `"1.2" -> (1, 2, 0)`
- `"1.2.3-rc1" -> (1, 2, 3)`
- `"10.0" -> (10, 0, 0)`

Keep the existing tuple API. Run `python -m pytest -q` from the repository root when you are done.
