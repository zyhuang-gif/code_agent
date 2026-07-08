import base64
import json
import pathlib
import subprocess
import sys

GOLDEN_PATCH_B64 = "ZGlmZiAtLWdpdCBhL3N5bXB5L3BoeXNpY3MvdW5pdHMvdGVzdHMvdGVzdF9xdWFudGl0aWVzLnB5IGIvc3ltcHkvcGh5c2ljcy91bml0cy90ZXN0cy90ZXN0X3F1YW50aXRpZXMucHkKLS0tIGEvc3ltcHkvcGh5c2ljcy91bml0cy90ZXN0cy90ZXN0X3F1YW50aXRpZXMucHkKKysrIGIvc3ltcHkvcGh5c2ljcy91bml0cy90ZXN0cy90ZXN0X3F1YW50aXRpZXMucHkKQEAgLTU2MSw2ICs1NjEsMjIgQEAgZGVmIHRlc3RfaXNzdWVfMjQwNjIoKToKICAgICBleHBfZXhwciA9IDEgKyBleHAoZXhwcikKICAgICBhc3NlcnQgU0kuX2NvbGxlY3RfZmFjdG9yX2FuZF9kaW1lbnNpb24oZXhwX2V4cHIpID09ICgxICsgRSwgRGltZW5zaW9uKDEpKQogCitkZWYgdGVzdF9pc3N1ZV8yNDIxMSgpOgorICAgIGZyb20gc3ltcHkucGh5c2ljcy51bml0cyBpbXBvcnQgdGltZSwgdmVsb2NpdHksIGFjY2VsZXJhdGlvbiwgc2Vjb25kLCBtZXRlcgorICAgIFYxID0gUXVhbnRpdHkoJ1YxJykKKyAgICBTSS5zZXRfcXVhbnRpdHlfZGltZW5zaW9uKFYxLCB2ZWxvY2l0eSkKKyAgICBTSS5zZXRfcXVhbnRpdHlfc2NhbGVfZmFjdG9yKFYxLCAxICogbWV0ZXIgLyBzZWNvbmQpCisgICAgQTEgPSBRdWFudGl0eSgnQTEnKQorICAgIFNJLnNldF9xdWFudGl0eV9kaW1lbnNpb24oQTEsIGFjY2VsZXJhdGlvbikKKyAgICBTSS5zZXRfcXVhbnRpdHlfc2NhbGVfZmFjdG9yKEExLCAxICogbWV0ZXIgLyBzZWNvbmQqKjIpCisgICAgVDEgPSBRdWFudGl0eSgnVDEnKQorICAgIFNJLnNldF9xdWFudGl0eV9kaW1lbnNpb24oVDEsIHRpbWUpCisgICAgU0kuc2V0X3F1YW50aXR5X3NjYWxlX2ZhY3RvcihUMSwgMSAqIHNlY29uZCkKKworICAgIGV4cHIgPSBBMSpUMSArIFYxCisgICAgIyBzaG91bGQgbm90IHRocm93IFZhbHVlRXJyb3IgaGVyZQorICAgIFNJLl9jb2xsZWN0X2ZhY3Rvcl9hbmRfZGltZW5zaW9uKGV4cHIpCisKIAogZGVmIHRlc3RfcHJlZml4ZWRfcHJvcGVydHkoKToKICAgICBhc3NlcnQgbm90IG1ldGVyLmlzX3ByZWZpeGVkCg=="

_TESTS = json.loads(r"""{"F2P": ["sympy/physics/units/tests/test_quantities.py::test_issue_24211"], "P2P": ["sympy/physics/units/tests/test_quantities.py::test_str_repr", "sympy/physics/units/tests/test_quantities.py::test_eq", "sympy/physics/units/tests/test_quantities.py::test_convert_to", "sympy/physics/units/tests/test_quantities.py::test_Quantity_definition", "sympy/physics/units/tests/test_quantities.py::test_abbrev", "sympy/physics/units/tests/test_quantities.py::test_print", "sympy/physics/units/tests/test_quantities.py::test_Quantity_eq", "sympy/physics/units/tests/test_quantities.py::test_add_sub", "sympy/physics/units/tests/test_quantities.py::test_quantity_abs", "sympy/physics/units/tests/test_quantities.py::test_check_unit_consistency", "sympy/physics/units/tests/test_quantities.py::test_mul_div", "sympy/physics/units/tests/test_quantities.py::test_units", "sympy/physics/units/tests/test_quantities.py::test_issue_quart", "sympy/physics/units/tests/test_quantities.py::test_issue_5565", "sympy/physics/units/tests/test_quantities.py::test_find_unit", "sympy/physics/units/tests/test_quantities.py::test_Quantity_derivative", "sympy/physics/units/tests/test_quantities.py::test_quantity_postprocessing", "sympy/physics/units/tests/test_quantities.py::test_factor_and_dimension", "sympy/physics/units/tests/test_quantities.py::test_dimensional_expr_of_derivative", "sympy/physics/units/tests/test_quantities.py::test_get_dimensional_expr_with_function", "sympy/physics/units/tests/test_quantities.py::test_binary_information", "sympy/physics/units/tests/test_quantities.py::test_conversion_with_2_nonstandard_dimensions", "sympy/physics/units/tests/test_quantities.py::test_eval_subs", "sympy/physics/units/tests/test_quantities.py::test_issue_14932", "sympy/physics/units/tests/test_quantities.py::test_issue_14547", "sympy/physics/units/tests/test_quantities.py::test_deprecated_quantity_methods", "sympy/physics/units/tests/test_quantities.py::test_issue_22164", "sympy/physics/units/tests/test_quantities.py::test_issue_22819", "sympy/physics/units/tests/test_quantities.py::test_issue_20288", "sympy/physics/units/tests/test_quantities.py::test_issue_24062", "sympy/physics/units/tests/test_quantities.py::test_prefixed_property"]}""")

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
