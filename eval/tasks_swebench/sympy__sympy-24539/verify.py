import base64
import json
import pathlib
import subprocess
import sys

GOLDEN_PATCH_B64 = "ZGlmZiAtLWdpdCBhL3N5bXB5L3BvbHlzL3Rlc3RzL3Rlc3RfcmluZ3MucHkgYi9zeW1weS9wb2x5cy90ZXN0cy90ZXN0X3JpbmdzLnB5Ci0tLSBhL3N5bXB5L3BvbHlzL3Rlc3RzL3Rlc3RfcmluZ3MucHkKKysrIGIvc3ltcHkvcG9seXMvdGVzdHMvdGVzdF9yaW5ncy5weQpAQCAtMjU5LDExICsyNTksMTEgQEAgZGVmIHRlc3RfUG9seUVsZW1lbnRfYXNfZXhwcigpOgogICAgIGFzc2VydCBmICE9IGcKICAgICBhc3NlcnQgZi5hc19leHByKCkgPT0gZwogCi0gICAgWCwgWSwgWiA9IHN5bWJvbHMoIngseSx6IikKLSAgICBnID0gMypYKioyKlkgLSBYKlkqWiArIDcqWioqMyArIDEKKyAgICBVLCBWLCBXID0gc3ltYm9scygidSx2LHciKQorICAgIGcgPSAzKlUqKjIqViAtIFUqVipXICsgNypXKiozICsgMQogCiAgICAgYXNzZXJ0IGYgIT0gZwotICAgIGFzc2VydCBmLmFzX2V4cHIoWCwgWSwgWikgPT0gZworICAgIGFzc2VydCBmLmFzX2V4cHIoVSwgViwgVykgPT0gZwogCiAgICAgcmFpc2VzKFZhbHVlRXJyb3IsIGxhbWJkYTogZi5hc19leHByKFgpKQogCg=="

_TESTS = json.loads(r"""{"F2P": ["test_PolyElement_as_expr"], "P2P": ["test_PolyRing___init__", "test_PolyRing___hash__", "test_PolyRing___eq__", "test_PolyRing_ring_new", "test_PolyRing_drop", "test_PolyRing___getitem__", "test_PolyRing_is_", "test_PolyRing_add", "test_PolyRing_mul", "test_sring", "test_PolyElement___hash__", "test_PolyElement___eq__", "test_PolyElement__lt_le_gt_ge__", "test_PolyElement__str__", "test_PolyElement_copy", "test_PolyElement_from_expr", "test_PolyElement_degree", "test_PolyElement_tail_degree", "test_PolyElement_degrees", "test_PolyElement_tail_degrees", "test_PolyElement_coeff", "test_PolyElement_LC", "test_PolyElement_LM", "test_PolyElement_LT", "test_PolyElement_leading_monom", "test_PolyElement_leading_term", "test_PolyElement_terms", "test_PolyElement_monoms", "test_PolyElement_coeffs", "test_PolyElement___add__", "test_PolyElement___sub__", "test_PolyElement___mul__", "test_PolyElement___truediv__", "test_PolyElement___pow__", "test_PolyElement_div", "test_PolyElement_rem", "test_PolyElement_deflate", "test_PolyElement_clear_denoms", "test_PolyElement_cofactors", "test_PolyElement_gcd", "test_PolyElement_cancel", "test_PolyElement_max_norm", "test_PolyElement_l1_norm", "test_PolyElement_diff", "test_PolyElement___call__", "test_PolyElement_evaluate", "test_PolyElement_subs", "test_PolyElement_compose", "test_PolyElement_is_", "test_PolyElement_drop", "test_PolyElement_pdiv", "test_PolyElement_gcdex", "test_PolyElement_subresultants", "test_PolyElement_resultant", "test_PolyElement_discriminant", "test_PolyElement_decompose", "test_PolyElement_shift", "test_PolyElement_sturm", "test_PolyElement_gff_list", "test_PolyElement_sqf_norm", "test_PolyElement_sqf_list", "test_PolyElement_factor_list"]}""")

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
