import base64
import json
import pathlib
import subprocess
import sys

GOLDEN_PATCH_B64 = "ZGlmZiAtLWdpdCBhL3N5bXB5L3V0aWxpdGllcy90ZXN0cy90ZXN0X2xhbWJkaWZ5LnB5IGIvc3ltcHkvdXRpbGl0aWVzL3Rlc3RzL3Rlc3RfbGFtYmRpZnkucHkKLS0tIGEvc3ltcHkvdXRpbGl0aWVzL3Rlc3RzL3Rlc3RfbGFtYmRpZnkucHkKKysrIGIvc3ltcHkvdXRpbGl0aWVzL3Rlc3RzL3Rlc3RfbGFtYmRpZnkucHkKQEAgLTExOTIsNiArMTE5Miw4IEBAIGRlZiB0ZXN0X2lzc3VlXzE0OTQxKCk6CiAgICAgIyB0ZXN0IHR1cGxlCiAgICAgZjIgPSBsYW1iZGlmeShbeCwgeV0sICh5LCB4KSwgJ3N5bXB5JykKICAgICBhc3NlcnQgZjIoMiwgMykgPT0gKDMsIDIpCisgICAgZjJiID0gbGFtYmRpZnkoW10sICgxLCkpICAjIGdoLTIzMjI0CisgICAgYXNzZXJ0IGYyYigpID09ICgxLCkKIAogICAgICMgdGVzdCBsaXN0CiAgICAgZjMgPSBsYW1iZGlmeShbeCwgeV0sIFt5LCB4XSwgJ3N5bXB5JykK"

_TESTS = json.loads(r"""{"F2P": ["sympy/utilities/tests/test_lambdify.py::test_issue_14941"], "P2P": ["sympy/utilities/tests/test_lambdify.py::test_no_args", "sympy/utilities/tests/test_lambdify.py::test_single_arg", "sympy/utilities/tests/test_lambdify.py::test_list_args", "sympy/utilities/tests/test_lambdify.py::test_nested_args", "sympy/utilities/tests/test_lambdify.py::test_str_args", "sympy/utilities/tests/test_lambdify.py::test_own_namespace_1", "sympy/utilities/tests/test_lambdify.py::test_own_namespace_2", "sympy/utilities/tests/test_lambdify.py::test_own_module", "sympy/utilities/tests/test_lambdify.py::test_bad_args", "sympy/utilities/tests/test_lambdify.py::test_atoms", "sympy/utilities/tests/test_lambdify.py::test_sympy_lambda", "sympy/utilities/tests/test_lambdify.py::test_math_lambda", "sympy/utilities/tests/test_lambdify.py::test_mpmath_lambda", "sympy/utilities/tests/test_lambdify.py::test_number_precision", "sympy/utilities/tests/test_lambdify.py::test_mpmath_precision", "sympy/utilities/tests/test_lambdify.py::test_math_transl", "sympy/utilities/tests/test_lambdify.py::test_mpmath_transl", "sympy/utilities/tests/test_lambdify.py::test_empty_modules", "sympy/utilities/tests/test_lambdify.py::test_exponentiation", "sympy/utilities/tests/test_lambdify.py::test_sqrt", "sympy/utilities/tests/test_lambdify.py::test_trig", "sympy/utilities/tests/test_lambdify.py::test_integral", "sympy/utilities/tests/test_lambdify.py::test_double_integral", "sympy/utilities/tests/test_lambdify.py::test_vector_simple", "sympy/utilities/tests/test_lambdify.py::test_vector_discontinuous", "sympy/utilities/tests/test_lambdify.py::test_trig_symbolic", "sympy/utilities/tests/test_lambdify.py::test_trig_float", "sympy/utilities/tests/test_lambdify.py::test_docs", "sympy/utilities/tests/test_lambdify.py::test_math", "sympy/utilities/tests/test_lambdify.py::test_sin", "sympy/utilities/tests/test_lambdify.py::test_matrix", "sympy/utilities/tests/test_lambdify.py::test_issue9474", "sympy/utilities/tests/test_lambdify.py::test_sym_single_arg", "sympy/utilities/tests/test_lambdify.py::test_sym_list_args", "sympy/utilities/tests/test_lambdify.py::test_sym_integral", "sympy/utilities/tests/test_lambdify.py::test_namespace_order", "sympy/utilities/tests/test_lambdify.py::test_imps", "sympy/utilities/tests/test_lambdify.py::test_imps_errors", "sympy/utilities/tests/test_lambdify.py::test_imps_wrong_args", "sympy/utilities/tests/test_lambdify.py::test_lambdify_imps", "sympy/utilities/tests/test_lambdify.py::test_dummification", "sympy/utilities/tests/test_lambdify.py::test_curly_matrix_symbol", "sympy/utilities/tests/test_lambdify.py::test_python_keywords", "sympy/utilities/tests/test_lambdify.py::test_lambdify_docstring", "sympy/utilities/tests/test_lambdify.py::test_special_printers", "sympy/utilities/tests/test_lambdify.py::test_true_false", "sympy/utilities/tests/test_lambdify.py::test_issue_2790", "sympy/utilities/tests/test_lambdify.py::test_issue_12092", "sympy/utilities/tests/test_lambdify.py::test_issue_14911", "sympy/utilities/tests/test_lambdify.py::test_ITE", "sympy/utilities/tests/test_lambdify.py::test_Min_Max", "sympy/utilities/tests/test_lambdify.py::test_issue_12173", "sympy/utilities/tests/test_lambdify.py::test_sinc_mpmath", "sympy/utilities/tests/test_lambdify.py::test_lambdify_dummy_arg", "sympy/utilities/tests/test_lambdify.py::test_lambdify_mixed_symbol_dummy_args", "sympy/utilities/tests/test_lambdify.py::test_lambdify_inspect", "sympy/utilities/tests/test_lambdify.py::test_lambdify_Derivative_arg_issue_16468", "sympy/utilities/tests/test_lambdify.py::test_imag_real", "sympy/utilities/tests/test_lambdify.py::test_single_e", "sympy/utilities/tests/test_lambdify.py::test_beta_math", "sympy/utilities/tests/test_lambdify.py::test_lambdify_cse"]}""")

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
