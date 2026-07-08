import base64
import json
import pathlib
import subprocess
import sys

GOLDEN_PATCH_B64 = "ZGlmZiAtLWdpdCBhL3N5bXB5L2dlb21ldHJ5L3Rlc3RzL3Rlc3RfcG9pbnQucHkgYi9zeW1weS9nZW9tZXRyeS90ZXN0cy90ZXN0X3BvaW50LnB5Ci0tLSBhL3N5bXB5L2dlb21ldHJ5L3Rlc3RzL3Rlc3RfcG9pbnQucHkKKysrIGIvc3ltcHkvZ2VvbWV0cnkvdGVzdHMvdGVzdF9wb2ludC5weQpAQCAtMSw1ICsxLDYgQEAKIGZyb20gc3ltcHkuY29yZS5iYXNpYyBpbXBvcnQgQmFzaWMKIGZyb20gc3ltcHkuY29yZS5udW1iZXJzIGltcG9ydCAoSSwgUmF0aW9uYWwsIHBpKQorZnJvbSBzeW1weS5jb3JlLnBhcmFtZXRlcnMgaW1wb3J0IGV2YWx1YXRlCiBmcm9tIHN5bXB5LmNvcmUuc2luZ2xldG9uIGltcG9ydCBTCiBmcm9tIHN5bXB5LmNvcmUuc3ltYm9sIGltcG9ydCBTeW1ib2wKIGZyb20gc3ltcHkuY29yZS5zeW1waWZ5IGltcG9ydCBzeW1waWZ5CkBAIC00NTIsNiArNDUzLDEyIEBAIGRlZiB0ZXN0X19ub3JtYWxpemVfZGltZW5zaW9uKCk6CiAgICAgICAgIFBvaW50KDEsIDIsIDApLCBQb2ludCgzLCA0LCAwKV0KIAogCitkZWYgdGVzdF9pc3N1ZV8yMjY4NCgpOgorICAgICMgVXNlZCB0byBnaXZlIGFuIGVycm9yCisgICAgd2l0aCBldmFsdWF0ZShGYWxzZSk6CisgICAgICAgIFBvaW50KDEsIDIpCisKKwogZGVmIHRlc3RfZGlyZWN0aW9uX2Nvc2luZSgpOgogICAgIHAxID0gUG9pbnQzRCgwLCAwLCAwKQogICAgIHAyID0gUG9pbnQzRCgxLCAxLCAxKQo="

_TESTS = json.loads(r"""{"F2P": ["sympy/geometry/tests/test_point.py::test_issue_22684"], "P2P": ["sympy/geometry/tests/test_point.py::test_point", "sympy/geometry/tests/test_point.py::test_point3D", "sympy/geometry/tests/test_point.py::test_Point2D", "sympy/geometry/tests/test_point.py::test_issue_9214", "sympy/geometry/tests/test_point.py::test_issue_11617", "sympy/geometry/tests/test_point.py::test_transform", "sympy/geometry/tests/test_point.py::test_concyclic_doctest_bug", "sympy/geometry/tests/test_point.py::test_arguments", "sympy/geometry/tests/test_point.py::test_unit", "sympy/geometry/tests/test_point.py::test_dot", "sympy/geometry/tests/test_point.py::test__normalize_dimension"]}""")

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
