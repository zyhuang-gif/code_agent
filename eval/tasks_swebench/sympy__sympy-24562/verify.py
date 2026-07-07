import base64
import json
import pathlib
import subprocess
import sys

GOLDEN_PATCH_B64 = "ZGlmZiAtLWdpdCBhL3N5bXB5L2NvcmUvdGVzdHMvdGVzdF9udW1iZXJzLnB5IGIvc3ltcHkvY29yZS90ZXN0cy90ZXN0X251bWJlcnMucHkKLS0tIGEvc3ltcHkvY29yZS90ZXN0cy90ZXN0X251bWJlcnMucHkKKysrIGIvc3ltcHkvY29yZS90ZXN0cy90ZXN0X251bWJlcnMucHkKQEAgLTM2Niw2ICszNjYsMTMgQEAgZGVmIHRlc3RfUmF0aW9uYWxfbmV3KCk6CiAgICAgYXNzZXJ0IG4ucSA9PSA0CiAgICAgYXNzZXJ0IG4ucCA9PSAtMgogCitkZWYgdGVzdF9pc3N1ZV8yNDU0MygpOgorICAgIGZvciBwIGluICgnMS41JywgMS41LCAyKToKKyAgICAgICAgZm9yIHEgaW4gKCcxLjUnLCAxLjUsIDIpOgorICAgICAgICAgICAgYXNzZXJ0IFJhdGlvbmFsKHAsIHEpLmFzX251bWVyX2Rlbm9tKCkgPT0gUmF0aW9uYWwoJyVzLyVzJyUocCxxKSkuYXNfbnVtZXJfZGVub20oKQorCisgICAgYXNzZXJ0IFJhdGlvbmFsKCcwLjUnLCAnMTAwJykgPT0gUmF0aW9uYWwoMSwgMjAwKQorCiAKIGRlZiB0ZXN0X051bWJlcl9uZXcoKToKICAgICAiIiIiCg=="

_TESTS = json.loads(r"""{"F2P": ["test_issue_24543"], "P2P": ["test_seterr", "test_mod", "test_divmod", "test_igcd", "test_igcd_lehmer", "test_igcd2", "test_ilcm", "test_igcdex", "test_Integer_new", "test_Rational_new", "test_Number_new", "test_Number_cmp", "test_Rational_cmp", "test_Float", "test_zero_not_false", "test_float_mpf", "test_Float_RealElement", "test_Float_default_to_highprec_from_str", "test_Float_eval", "test_Float_issue_2107", "test_issue_14289", "test_Float_from_tuple", "test_Infinity", "test_Infinity_2", "test_Mul_Infinity_Zero", "test_Div_By_Zero", "test_Infinity_inequations", "test_NaN", "test_special_numbers", "test_powers", "test_integer_nthroot_overflow", "test_integer_log", "test_isqrt", "test_powers_Integer", "test_powers_Rational", "test_powers_Float", "test_lshift_Integer", "test_rshift_Integer", "test_and_Integer", "test_xor_Integer", "test_or_Integer", "test_invert_Integer", "test_abs1", "test_accept_int", "test_dont_accept_str", "test_int", "test_int_NumberSymbols", "test_real_bug", "test_bug_sqrt", "test_pi_Pi", "test_no_len", "test_issue_3321", "test_issue_3692", "test_issue_3423", "test_issue_3449", "test_issue_13890", "test_Integer_factors", "test_Rational_factors", "test_issue_4107", "test_IntegerInteger", "test_Rational_gcd_lcm_cofactors", "test_Float_gcd_lcm_cofactors", "test_issue_4611", "test_conversion_to_mpmath", "test_relational", "test_Integer_as_index", "test_Rational_int", "test_zoo", "test_issue_4122", "test_GoldenRatio_expand", "test_TribonacciConstant_expand", "test_as_content_primitive", "test_hashing_sympy_integers", "test_rounding_issue_4172", "test_Catalan_EulerGamma_prec", "test_Catalan_rewrite", "test_bool_eq", "test_Float_eq", "test_issue_6640", "test_issue_6349", "test_mpf_norm", "test_latex", "test_issue_7742", "test_simplify_AlgebraicNumber", "test_Float_idempotence", "test_comp1", "test_issue_9491", "test_issue_10063", "test_issue_10020", "test_invert_numbers", "test_mod_inverse", "test_golden_ratio_rewrite_as_sqrt", "test_tribonacci_constant_rewrite_as_sqrt", "test_comparisons_with_unknown_type", "test_NumberSymbol_comparison", "test_Integer_precision", "test_Integer_ceiling_floor", "test_ComplexInfinity", "test_Infinity_floor_ceiling_power", "test_One_power", "test_NegativeInfinity", "test_issue_6133", "test_abc", "test_floordiv", "test_negation"]}""")

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
