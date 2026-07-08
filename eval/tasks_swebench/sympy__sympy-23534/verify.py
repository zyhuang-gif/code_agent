import base64
import json
import pathlib
import subprocess
import sys

GOLDEN_PATCH_B64 = "ZGlmZiAtLWdpdCBhL3N5bXB5L2NvcmUvdGVzdHMvdGVzdF9zeW1ib2wucHkgYi9zeW1weS9jb3JlL3Rlc3RzL3Rlc3Rfc3ltYm9sLnB5Ci0tLSBhL3N5bXB5L2NvcmUvdGVzdHMvdGVzdF9zeW1ib2wucHkKKysrIGIvc3ltcHkvY29yZS90ZXN0cy90ZXN0X3N5bWJvbC5weQpAQCAtMSwzICsxLDQgQEAKK2Zyb20gc3ltcHkuY29yZS5mdW5jdGlvbiBpbXBvcnQgRnVuY3Rpb24sIFVuZGVmaW5lZEZ1bmN0aW9uCiBmcm9tIHN5bXB5LmNvcmUubnVtYmVycyBpbXBvcnQgKEksIFJhdGlvbmFsLCBwaSkKIGZyb20gc3ltcHkuY29yZS5yZWxhdGlvbmFsIGltcG9ydCAoR3JlYXRlclRoYW4sIExlc3NUaGFuLCBTdHJpY3RHcmVhdGVyVGhhbiwgU3RyaWN0TGVzc1RoYW4pCiBmcm9tIHN5bXB5LmNvcmUuc3ltYm9sIGltcG9ydCAoRHVtbXksIFN5bWJvbCwgV2lsZCwgc3ltYm9scykKQEAgLTI5NCw2ICsyOTUsNyBAQCBkZWYgdGVzdF9zeW1ib2xzKCk6CiAgICAgYXNzZXJ0IHN5bWJvbHMoJ2FhOmQseDp6JykgPT0gKGFhLCBhYiwgYWMsIGFkLCB4LCB5LCB6KQogICAgIGFzc2VydCBzeW1ib2xzKCgnYWE6ZCcsJ3g6eicpKSA9PSAoKGFhLCBhYiwgYWMsIGFkKSwgKHgsIHksIHopKQogCisgICAgYXNzZXJ0IHR5cGUoc3ltYm9scygoJ3E6MicsICd1OjInKSwgY2xzPUZ1bmN0aW9uKVswXVswXSkgPT0gVW5kZWZpbmVkRnVuY3Rpb24gICMgaXNzdWUgMjM1MzIKIAogICAgICMgaXNzdWUgNjY3NQogICAgIGRlZiBzeW0ocyk6Cg=="

_TESTS = json.loads(r"""{"F2P": ["sympy/core/tests/test_symbol.py::test_symbols"], "P2P": ["sympy/core/tests/test_symbol.py::test_Str", "sympy/core/tests/test_symbol.py::test_Symbol", "sympy/core/tests/test_symbol.py::test_Dummy", "sympy/core/tests/test_symbol.py::test_Dummy_force_dummy_index", "sympy/core/tests/test_symbol.py::test_lt_gt", "sympy/core/tests/test_symbol.py::test_no_len", "sympy/core/tests/test_symbol.py::test_ineq_unequal", "sympy/core/tests/test_symbol.py::test_Wild_properties", "sympy/core/tests/test_symbol.py::test_symbols_become_functions_issue_3539", "sympy/core/tests/test_symbol.py::test_unicode", "sympy/core/tests/test_symbol.py::test_uniquely_named_symbol_and_Symbol"]}""")

patch_bytes = base64.b64decode(GOLDEN_PATCH_B64)
patch_path = pathlib.Path("_test_patch.diff")
patch_path.write_bytes(patch_bytes)

proc = subprocess.run(
    ["git", "apply", str(patch_path)],
    capture_output=True, text=True, timeout=30
)
if proc.returncode != 0:
    print(f"Patch apply failed: {proc.stderr}", file=sys.stderr)
    raise SystemExit(2)

cmd = [sys.executable, "-m", "pytest", *_TESTS["F2P"], *_TESTS["P2P"], "-q", "-p", "no:cacheprovider"]
proc = subprocess.run(cmd, text=True, capture_output=True, timeout=600)
print(proc.stdout, end="")
print(proc.stderr, end="")
raise SystemExit(proc.returncode)
