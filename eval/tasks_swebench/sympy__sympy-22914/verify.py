import base64
import json
import pathlib
import subprocess
import sys

GOLDEN_PATCH_B64 = "ZGlmZiAtLWdpdCBhL3N5bXB5L3ByaW50aW5nL3Rlc3RzL3Rlc3RfcHljb2RlLnB5IGIvc3ltcHkvcHJpbnRpbmcvdGVzdHMvdGVzdF9weWNvZGUucHkKLS0tIGEvc3ltcHkvcHJpbnRpbmcvdGVzdHMvdGVzdF9weWNvZGUucHkKKysrIGIvc3ltcHkvcHJpbnRpbmcvdGVzdHMvdGVzdF9weWNvZGUucHkKQEAgLTYsNyArNiw3IEBACiBmcm9tIHN5bXB5LmNvcmUgaW1wb3J0IEV4cHIsIE1vZCwgc3ltYm9scywgRXEsIExlLCBHdCwgem9vLCBvbywgUmF0aW9uYWwsIFBvdwogZnJvbSBzeW1weS5jb3JlLm51bWJlcnMgaW1wb3J0IHBpCiBmcm9tIHN5bXB5LmNvcmUuc2luZ2xldG9uIGltcG9ydCBTCi1mcm9tIHN5bXB5LmZ1bmN0aW9ucyBpbXBvcnQgYWNvcywgS3JvbmVja2VyRGVsdGEsIFBpZWNld2lzZSwgc2lnbiwgc3FydAorZnJvbSBzeW1weS5mdW5jdGlvbnMgaW1wb3J0IGFjb3MsIEtyb25lY2tlckRlbHRhLCBQaWVjZXdpc2UsIHNpZ24sIHNxcnQsIE1pbiwgTWF4CiBmcm9tIHN5bXB5LmxvZ2ljIGltcG9ydCBBbmQsIE9yCiBmcm9tIHN5bXB5Lm1hdHJpY2VzIGltcG9ydCBTcGFyc2VNYXRyaXgsIE1hdHJpeFN5bWJvbCwgSWRlbnRpdHkKIGZyb20gc3ltcHkucHJpbnRpbmcucHljb2RlIGltcG9ydCAoCkBAIC01OCw2ICs1OCw5IEBAIGRlZiB0ZXN0X1B5dGhvbkNvZGVQcmludGVyKCk6CiAgICAgYXNzZXJ0IHBybnRyLmRvcHJpbnQoKDIsMykpID09ICIoMiwgMykiCiAgICAgYXNzZXJ0IHBybnRyLmRvcHJpbnQoWzIsM10pID09ICJbMiwgM10iCiAKKyAgICBhc3NlcnQgcHJudHIuZG9wcmludChNaW4oeCwgeSkpID09ICJtaW4oeCwgeSkiCisgICAgYXNzZXJ0IHBybnRyLmRvcHJpbnQoTWF4KHgsIHkpKSA9PSAibWF4KHgsIHkpIgorCiAKIGRlZiB0ZXN0X1B5dGhvbkNvZGVQcmludGVyX3N0YW5kYXJkKCk6CiAgICAgcHJudHIgPSBQeXRob25Db2RlUHJpbnRlcigpCg=="

_TESTS = json.loads(r"""{"F2P": ["sympy/printing/tests/test_pycode.py::test_PythonCodePrinter"], "P2P": ["sympy/printing/tests/test_pycode.py::test_PythonCodePrinter_standard", "sympy/printing/tests/test_pycode.py::test_MpmathPrinter", "sympy/printing/tests/test_pycode.py::test_NumPyPrinter", "sympy/printing/tests/test_pycode.py::test_SciPyPrinter", "sympy/printing/tests/test_pycode.py::test_pycode_reserved_words", "sympy/printing/tests/test_pycode.py::test_sqrt", "sympy/printing/tests/test_pycode.py::test_frac", "sympy/printing/tests/test_pycode.py::test_printmethod", "sympy/printing/tests/test_pycode.py::test_codegen_ast_nodes", "sympy/printing/tests/test_pycode.py::test_issue_14283", "sympy/printing/tests/test_pycode.py::test_NumPyPrinter_print_seq", "sympy/printing/tests/test_pycode.py::test_issue_16535_16536", "sympy/printing/tests/test_pycode.py::test_Integral", "sympy/printing/tests/test_pycode.py::test_fresnel_integrals", "sympy/printing/tests/test_pycode.py::test_beta", "sympy/printing/tests/test_pycode.py::test_airy", "sympy/printing/tests/test_pycode.py::test_airy_prime"]}""")

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
