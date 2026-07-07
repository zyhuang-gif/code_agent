import base64
import json
import pathlib
import subprocess
import sys

GOLDEN_PATCH_B64 = "ZGlmZiAtLWdpdCBhL3N5bXB5L3BoeXNpY3MvdW5pdHMvdGVzdHMvdGVzdF9xdWFudGl0aWVzLnB5IGIvc3ltcHkvcGh5c2ljcy91bml0cy90ZXN0cy90ZXN0X3F1YW50aXRpZXMucHkKLS0tIGEvc3ltcHkvcGh5c2ljcy91bml0cy90ZXN0cy90ZXN0X3F1YW50aXRpZXMucHkKKysrIGIvc3ltcHkvcGh5c2ljcy91bml0cy90ZXN0cy90ZXN0X3F1YW50aXRpZXMucHkKQEAgLTU2MSw2ICs1NjEsMjIgQEAgZGVmIHRlc3RfaXNzdWVfMjQwNjIoKToKICAgICBleHBfZXhwciA9IDEgKyBleHAoZXhwcikKICAgICBhc3NlcnQgU0kuX2NvbGxlY3RfZmFjdG9yX2FuZF9kaW1lbnNpb24oZXhwX2V4cHIpID09ICgxICsgRSwgRGltZW5zaW9uKDEpKQogCitkZWYgdGVzdF9pc3N1ZV8yNDIxMSgpOgorICAgIGZyb20gc3ltcHkucGh5c2ljcy51bml0cyBpbXBvcnQgdGltZSwgdmVsb2NpdHksIGFjY2VsZXJhdGlvbiwgc2Vjb25kLCBtZXRlcgorICAgIFYxID0gUXVhbnRpdHkoJ1YxJykKKyAgICBTSS5zZXRfcXVhbnRpdHlfZGltZW5zaW9uKFYxLCB2ZWxvY2l0eSkKKyAgICBTSS5zZXRfcXVhbnRpdHlfc2NhbGVfZmFjdG9yKFYxLCAxICogbWV0ZXIgLyBzZWNvbmQpCisgICAgQTEgPSBRdWFudGl0eSgnQTEnKQorICAgIFNJLnNldF9xdWFudGl0eV9kaW1lbnNpb24oQTEsIGFjY2VsZXJhdGlvbikKKyAgICBTSS5zZXRfcXVhbnRpdHlfc2NhbGVfZmFjdG9yKEExLCAxICogbWV0ZXIgLyBzZWNvbmQqKjIpCisgICAgVDEgPSBRdWFudGl0eSgnVDEnKQorICAgIFNJLnNldF9xdWFudGl0eV9kaW1lbnNpb24oVDEsIHRpbWUpCisgICAgU0kuc2V0X3F1YW50aXR5X3NjYWxlX2ZhY3RvcihUMSwgMSAqIHNlY29uZCkKKworICAgIGV4cHIgPSBBMSpUMSArIFYxCisgICAgIyBzaG91bGQgbm90IHRocm93IFZhbHVlRXJyb3IgaGVyZQorICAgIFNJLl9jb2xsZWN0X2ZhY3Rvcl9hbmRfZGltZW5zaW9uKGV4cHIpCisKIAogZGVmIHRlc3RfcHJlZml4ZWRfcHJvcGVydHkoKToKICAgICBhc3NlcnQgbm90IG1ldGVyLmlzX3ByZWZpeGVkCg=="

_TESTS = json.loads(r"""{"F2P": ["test_issue_24211"], "P2P": ["test_str_repr", "test_eq", "test_convert_to", "test_Quantity_definition", "test_abbrev", "test_print", "test_Quantity_eq", "test_add_sub", "test_quantity_abs", "test_check_unit_consistency", "test_mul_div", "test_units", "test_issue_quart", "test_issue_5565", "test_find_unit", "test_Quantity_derivative", "test_quantity_postprocessing", "test_factor_and_dimension", "test_dimensional_expr_of_derivative", "test_get_dimensional_expr_with_function", "test_binary_information", "test_conversion_with_2_nonstandard_dimensions", "test_eval_subs", "test_issue_14932", "test_issue_14547", "test_deprecated_quantity_methods", "test_issue_22164", "test_issue_22819", "test_issue_20288", "test_issue_24062", "test_prefixed_property"]}""")

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
