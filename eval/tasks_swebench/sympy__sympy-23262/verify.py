import base64
import json
import pathlib
import subprocess
import sys

GOLDEN_PATCH_B64 = "ZGlmZiAtLWdpdCBhL3N5bXB5L3V0aWxpdGllcy90ZXN0cy90ZXN0X2xhbWJkaWZ5LnB5IGIvc3ltcHkvdXRpbGl0aWVzL3Rlc3RzL3Rlc3RfbGFtYmRpZnkucHkKLS0tIGEvc3ltcHkvdXRpbGl0aWVzL3Rlc3RzL3Rlc3RfbGFtYmRpZnkucHkKKysrIGIvc3ltcHkvdXRpbGl0aWVzL3Rlc3RzL3Rlc3RfbGFtYmRpZnkucHkKQEAgLTExOTIsNiArMTE5Miw4IEBAIGRlZiB0ZXN0X2lzc3VlXzE0OTQxKCk6CiAgICAgIyB0ZXN0IHR1cGxlCiAgICAgZjIgPSBsYW1iZGlmeShbeCwgeV0sICh5LCB4KSwgJ3N5bXB5JykKICAgICBhc3NlcnQgZjIoMiwgMykgPT0gKDMsIDIpCisgICAgZjJiID0gbGFtYmRpZnkoW10sICgxLCkpICAjIGdoLTIzMjI0CisgICAgYXNzZXJ0IGYyYigpID09ICgxLCkKIAogICAgICMgdGVzdCBsaXN0CiAgICAgZjMgPSBsYW1iZGlmeShbeCwgeV0sIFt5LCB4XSwgJ3N5bXB5JykK"

_TESTS = json.loads(r"""{"F2P": ["test_issue_14941"], "P2P": ["test_no_args", "test_single_arg", "test_list_args", "test_nested_args", "test_str_args", "test_own_namespace_1", "test_own_namespace_2", "test_own_module", "test_bad_args", "test_atoms", "test_sympy_lambda", "test_math_lambda", "test_mpmath_lambda", "test_number_precision", "test_mpmath_precision", "test_math_transl", "test_mpmath_transl", "test_empty_modules", "test_exponentiation", "test_sqrt", "test_trig", "test_integral", "test_double_integral", "test_vector_simple", "test_vector_discontinuous", "test_trig_symbolic", "test_trig_float", "test_docs", "test_math", "test_sin", "test_matrix", "test_issue9474", "test_sym_single_arg", "test_sym_list_args", "test_sym_integral", "test_namespace_order", "test_imps", "test_imps_errors", "test_imps_wrong_args", "test_lambdify_imps", "test_dummification", "test_curly_matrix_symbol", "test_python_keywords", "test_lambdify_docstring", "test_special_printers", "test_true_false", "test_issue_2790", "test_issue_12092", "test_issue_14911", "test_ITE", "test_Min_Max", "test_issue_12173", "test_sinc_mpmath", "test_lambdify_dummy_arg", "test_lambdify_mixed_symbol_dummy_args", "test_lambdify_inspect", "test_lambdify_Derivative_arg_issue_16468", "test_imag_real", "test_single_e", "test_beta_math", "test_lambdify_cse"]}""")

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
