import base64
import json
import pathlib
import subprocess
import sys

GOLDEN_PATCH_B64 = "ZGlmZiAtLWdpdCBhL3N5bXB5L3NldHMvdGVzdHMvdGVzdF9jb250YWlucy5weSBiL3N5bXB5L3NldHMvdGVzdHMvdGVzdF9jb250YWlucy5weQotLS0gYS9zeW1weS9zZXRzL3Rlc3RzL3Rlc3RfY29udGFpbnMucHkKKysrIGIvc3ltcHkvc2V0cy90ZXN0cy90ZXN0X2NvbnRhaW5zLnB5CkBAIC00MSwxMCArNDEsOSBAQCBkZWYgdGVzdF9iaW5hcnlfc3ltYm9scygpOgogZGVmIHRlc3RfYXNfc2V0KCk6CiAgICAgeCA9IFN5bWJvbCgneCcpCiAgICAgeSA9IFN5bWJvbCgneScpCi0gICAgIyBDb250YWlucyBpcyBhIEJvb2xlYW5GdW5jdGlvbiB3aG9zZSB2YWx1ZSBkZXBlbmRzIG9uIGFuIGFyZydzCi0gICAgIyBjb250YWlubWVudCBpbiBhIFNldCAtLSByZXdyaXRpbmcgYXMgYSBTZXQgaXMgbm90IHlldCBpbXBsZW1lbnRlZAotICAgIHJhaXNlcyhOb3RJbXBsZW1lbnRlZEVycm9yLCBsYW1iZGE6Ci0gICAgICAgICAgIENvbnRhaW5zKHgsIEZpbml0ZVNldCh5KSkuYXNfc2V0KCkpCisgICAgYXNzZXJ0IENvbnRhaW5zKHgsIEZpbml0ZVNldCh5KSkuYXNfc2V0KCkgPT0gRmluaXRlU2V0KHkpCisgICAgYXNzZXJ0IENvbnRhaW5zKHgsIFMuSW50ZWdlcnMpLmFzX3NldCgpID09IFMuSW50ZWdlcnMKKyAgICBhc3NlcnQgQ29udGFpbnMoeCwgUy5SZWFscykuYXNfc2V0KCkgPT0gUy5SZWFscwogCiBkZWYgdGVzdF90eXBlX2Vycm9yKCk6CiAgICAgIyBQYXNzIGluIGEgcGFyYW1ldGVyIG5vdCBvZiB0eXBlICJzZXQiCg=="

_TESTS = json.loads(r"""{"F2P": ["sympy/sets/tests/test_contains.py::test_as_set"], "P2P": ["sympy/sets/tests/test_contains.py::test_contains_basic", "sympy/sets/tests/test_contains.py::test_issue_6194", "sympy/sets/tests/test_contains.py::test_issue_10326", "sympy/sets/tests/test_contains.py::test_binary_symbols"]}""")

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
