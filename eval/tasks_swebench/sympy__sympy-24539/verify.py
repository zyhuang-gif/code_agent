import base64
import json
import pathlib
import subprocess
import sys

GOLDEN_PATCH_B64 = "ZGlmZiAtLWdpdCBhL3N5bXB5L3BvbHlzL3Rlc3RzL3Rlc3RfcmluZ3MucHkgYi9zeW1weS9wb2x5cy90ZXN0cy90ZXN0X3JpbmdzLnB5Ci0tLSBhL3N5bXB5L3BvbHlzL3Rlc3RzL3Rlc3RfcmluZ3MucHkKKysrIGIvc3ltcHkvcG9seXMvdGVzdHMvdGVzdF9yaW5ncy5weQpAQCAtMjU5LDExICsyNTksMTEgQEAgZGVmIHRlc3RfUG9seUVsZW1lbnRfYXNfZXhwcigpOgogICAgIGFzc2VydCBmICE9IGcKICAgICBhc3NlcnQgZi5hc19leHByKCkgPT0gZwogCi0gICAgWCwgWSwgWiA9IHN5bWJvbHMoIngseSx6IikKLSAgICBnID0gMypYKioyKlkgLSBYKlkqWiArIDcqWioqMyArIDEKKyAgICBVLCBWLCBXID0gc3ltYm9scygidSx2LHciKQorICAgIGcgPSAzKlUqKjIqViAtIFUqVipXICsgNypXKiozICsgMQogCiAgICAgYXNzZXJ0IGYgIT0gZwotICAgIGFzc2VydCBmLmFzX2V4cHIoWCwgWSwgWikgPT0gZworICAgIGFzc2VydCBmLmFzX2V4cHIoVSwgViwgVykgPT0gZwogCiAgICAgcmFpc2VzKFZhbHVlRXJyb3IsIGxhbWJkYTogZi5hc19leHByKFgpKQogCg=="

_TESTS = json.loads(r"""{"F2P": ["sympy/polys/tests/test_rings.py::test_PolyElement_as_expr"], "P2P": ["sympy/polys/tests/test_rings.py::test_PolyRing___init__", "sympy/polys/tests/test_rings.py::test_PolyRing___hash__", "sympy/polys/tests/test_rings.py::test_PolyRing___eq__", "sympy/polys/tests/test_rings.py::test_PolyRing_ring_new", "sympy/polys/tests/test_rings.py::test_PolyRing_drop", "sympy/polys/tests/test_rings.py::test_PolyRing___getitem__", "sympy/polys/tests/test_rings.py::test_PolyRing_is_", "sympy/polys/tests/test_rings.py::test_PolyRing_add", "sympy/polys/tests/test_rings.py::test_PolyRing_mul", "sympy/polys/tests/test_rings.py::test_sring", "sympy/polys/tests/test_rings.py::test_PolyElement___hash__", "sympy/polys/tests/test_rings.py::test_PolyElement___eq__", "sympy/polys/tests/test_rings.py::test_PolyElement__lt_le_gt_ge__", "sympy/polys/tests/test_rings.py::test_PolyElement__str__", "sympy/polys/tests/test_rings.py::test_PolyElement_copy", "sympy/polys/tests/test_rings.py::test_PolyElement_from_expr", "sympy/polys/tests/test_rings.py::test_PolyElement_degree", "sympy/polys/tests/test_rings.py::test_PolyElement_tail_degree", "sympy/polys/tests/test_rings.py::test_PolyElement_degrees", "sympy/polys/tests/test_rings.py::test_PolyElement_tail_degrees", "sympy/polys/tests/test_rings.py::test_PolyElement_coeff", "sympy/polys/tests/test_rings.py::test_PolyElement_LC", "sympy/polys/tests/test_rings.py::test_PolyElement_LM", "sympy/polys/tests/test_rings.py::test_PolyElement_LT", "sympy/polys/tests/test_rings.py::test_PolyElement_leading_monom", "sympy/polys/tests/test_rings.py::test_PolyElement_leading_term", "sympy/polys/tests/test_rings.py::test_PolyElement_terms", "sympy/polys/tests/test_rings.py::test_PolyElement_monoms", "sympy/polys/tests/test_rings.py::test_PolyElement_coeffs", "sympy/polys/tests/test_rings.py::test_PolyElement___add__", "sympy/polys/tests/test_rings.py::test_PolyElement___sub__", "sympy/polys/tests/test_rings.py::test_PolyElement___mul__", "sympy/polys/tests/test_rings.py::test_PolyElement___truediv__", "sympy/polys/tests/test_rings.py::test_PolyElement___pow__", "sympy/polys/tests/test_rings.py::test_PolyElement_div", "sympy/polys/tests/test_rings.py::test_PolyElement_rem", "sympy/polys/tests/test_rings.py::test_PolyElement_deflate", "sympy/polys/tests/test_rings.py::test_PolyElement_clear_denoms", "sympy/polys/tests/test_rings.py::test_PolyElement_cofactors", "sympy/polys/tests/test_rings.py::test_PolyElement_gcd", "sympy/polys/tests/test_rings.py::test_PolyElement_cancel", "sympy/polys/tests/test_rings.py::test_PolyElement_max_norm", "sympy/polys/tests/test_rings.py::test_PolyElement_l1_norm", "sympy/polys/tests/test_rings.py::test_PolyElement_diff", "sympy/polys/tests/test_rings.py::test_PolyElement___call__", "sympy/polys/tests/test_rings.py::test_PolyElement_evaluate", "sympy/polys/tests/test_rings.py::test_PolyElement_subs", "sympy/polys/tests/test_rings.py::test_PolyElement_compose", "sympy/polys/tests/test_rings.py::test_PolyElement_is_", "sympy/polys/tests/test_rings.py::test_PolyElement_drop", "sympy/polys/tests/test_rings.py::test_PolyElement_pdiv", "sympy/polys/tests/test_rings.py::test_PolyElement_gcdex", "sympy/polys/tests/test_rings.py::test_PolyElement_subresultants", "sympy/polys/tests/test_rings.py::test_PolyElement_resultant", "sympy/polys/tests/test_rings.py::test_PolyElement_discriminant", "sympy/polys/tests/test_rings.py::test_PolyElement_decompose", "sympy/polys/tests/test_rings.py::test_PolyElement_shift", "sympy/polys/tests/test_rings.py::test_PolyElement_sturm", "sympy/polys/tests/test_rings.py::test_PolyElement_gff_list", "sympy/polys/tests/test_rings.py::test_PolyElement_sqf_norm", "sympy/polys/tests/test_rings.py::test_PolyElement_sqf_list", "sympy/polys/tests/test_rings.py::test_PolyElement_factor_list"]}""")

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
