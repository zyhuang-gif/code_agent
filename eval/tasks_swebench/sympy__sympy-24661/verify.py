import base64
import json
import pathlib
import subprocess
import sys

GOLDEN_PATCH_B64 = "ZGlmZiAtLWdpdCBhL3N5bXB5L3BhcnNpbmcvdGVzdHMvdGVzdF9zeW1weV9wYXJzZXIucHkgYi9zeW1weS9wYXJzaW5nL3Rlc3RzL3Rlc3Rfc3ltcHlfcGFyc2VyLnB5Ci0tLSBhL3N5bXB5L3BhcnNpbmcvdGVzdHMvdGVzdF9zeW1weV9wYXJzZXIucHkKKysrIGIvc3ltcHkvcGFyc2luZy90ZXN0cy90ZXN0X3N5bXB5X3BhcnNlci5weQpAQCAtNiw3ICs2LDcgQEAKIGltcG9ydCB0eXBlcwogCiBmcm9tIHN5bXB5LmFzc3VtcHRpb25zIGltcG9ydCBRCi1mcm9tIHN5bXB5LmNvcmUgaW1wb3J0IFN5bWJvbCwgRnVuY3Rpb24sIEZsb2F0LCBSYXRpb25hbCwgSW50ZWdlciwgSSwgTXVsLCBQb3csIEVxCitmcm9tIHN5bXB5LmNvcmUgaW1wb3J0IFN5bWJvbCwgRnVuY3Rpb24sIEZsb2F0LCBSYXRpb25hbCwgSW50ZWdlciwgSSwgTXVsLCBQb3csIEVxLCBMdCwgTGUsIEd0LCBHZSwgTmUKIGZyb20gc3ltcHkuZnVuY3Rpb25zIGltcG9ydCBleHAsIGZhY3RvcmlhbCwgZmFjdG9yaWFsMiwgc2luLCBNaW4sIE1heAogZnJvbSBzeW1weS5sb2dpYyBpbXBvcnQgQW5kCiBmcm9tIHN5bXB5LnNlcmllcyBpbXBvcnQgTGltaXQKQEAgLTI3OSw2ICsyNzksMTcgQEAgZGVmIHRlc3RfcGFyc2VfZnVuY3Rpb25faXNzdWVfMzUzOSgpOgogICAgIGYgPSBGdW5jdGlvbignZicpCiAgICAgYXNzZXJ0IHBhcnNlX2V4cHIoJ2YoeCknKSA9PSBmKHgpCiAKK2RlZiB0ZXN0X2lzc3VlXzI0Mjg4KCk6CisgICAgaW5wdXRzID0geworICAgICAgICAiMSA8IDIiOiBMdCgxLCAyLCBldmFsdWF0ZT1GYWxzZSksCisgICAgICAgICIxIDw9IDIiOiBMZSgxLCAyLCBldmFsdWF0ZT1GYWxzZSksCisgICAgICAgICIxID4gMiI6IEd0KDEsIDIsIGV2YWx1YXRlPUZhbHNlKSwKKyAgICAgICAgIjEgPj0gMiI6IEdlKDEsIDIsIGV2YWx1YXRlPUZhbHNlKSwKKyAgICAgICAgIjEgIT0gMiI6IE5lKDEsIDIsIGV2YWx1YXRlPUZhbHNlKSwKKyAgICAgICAgIjEgPT0gMiI6IEVxKDEsIDIsIGV2YWx1YXRlPUZhbHNlKQorICAgIH0KKyAgICBmb3IgdGV4dCwgcmVzdWx0IGluIGlucHV0cy5pdGVtcygpOgorICAgICAgICBhc3NlcnQgcGFyc2VfZXhwcih0ZXh0LCBldmFsdWF0ZT1GYWxzZSkgPT0gcmVzdWx0CiAKIGRlZiB0ZXN0X3NwbGl0X3N5bWJvbHNfbnVtZXJpYygpOgogICAgIHRyYW5zZm9ybWF0aW9ucyA9ICgK"

_TESTS = json.loads(r"""{"F2P": ["test_issue_24288"], "P2P": ["test_sympy_parser", "test_rationalize", "test_factorial_fail", "test_repeated_fail", "test_repeated_dot_only", "test_local_dict", "test_local_dict_split_implmult", "test_local_dict_symbol_to_fcn", "test_global_dict", "test_no_globals", "test_issue_2515", "test_issue_7663", "test_recursive_evaluate_false_10560", "test_function_evaluate_false", "test_issue_10773", "test_split_symbols", "test_split_symbols_function", "test_functional_exponent", "test_match_parentheses_implicit_multiplication", "test_convert_equals_signs", "test_parse_function_issue_3539", "test_split_symbols_numeric", "test_unicode_names", "test_python3_features", "test_issue_19501", "test_parsing_definitions", "test_builtins"]}""")

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
