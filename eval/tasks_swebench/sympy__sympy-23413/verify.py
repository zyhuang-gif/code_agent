import base64
import json
import pathlib
import subprocess
import sys

GOLDEN_PATCH_B64 = "ZGlmZiAtLWdpdCBhL3N5bXB5L21hdHJpY2VzL3Rlc3RzL3Rlc3Rfbm9ybWFsZm9ybXMucHkgYi9zeW1weS9tYXRyaWNlcy90ZXN0cy90ZXN0X25vcm1hbGZvcm1zLnB5Ci0tLSBhL3N5bXB5L21hdHJpY2VzL3Rlc3RzL3Rlc3Rfbm9ybWFsZm9ybXMucHkKKysrIGIvc3ltcHkvbWF0cmljZXMvdGVzdHMvdGVzdF9ub3JtYWxmb3Jtcy5weQpAQCAtNzcsNSArNzcsMTEgQEAgZGVmIHRlc3RfaGVybWl0ZV9ub3JtYWwoKToKICAgICBhc3NlcnQgaGVybWl0ZV9ub3JtYWxfZm9ybShtKSA9PSBobmYKIAogICAgIG0gPSBNYXRyaXgoW1syLCA3XSwgWzAsIDBdLCBbMCwgMF1dKQotICAgIGhuZiA9IE1hdHJpeCgzLCAwLCBbXSkKKyAgICBobmYgPSBNYXRyaXgoW1sxXSwgWzBdLCBbMF1dKQogICAgIGFzc2VydCBoZXJtaXRlX25vcm1hbF9mb3JtKG0pID09IGhuZgorCisKK2RlZiB0ZXN0X2lzc3VlXzIzNDEwKCk6CisgICAgQSA9IE1hdHJpeChbWzEsIDEyXSwgWzAsIDhdLCBbMCwgNV1dKQorICAgIEggPSBNYXRyaXgoW1sxLCAwXSwgWzAsIDhdLCBbMCwgNV1dKQorICAgIGFzc2VydCBoZXJtaXRlX25vcm1hbF9mb3JtKEEpID09IEgKZGlmZiAtLWdpdCBhL3N5bXB5L3BvbHlzL21hdHJpY2VzL3Rlc3RzL3Rlc3Rfbm9ybWFsZm9ybXMucHkgYi9zeW1weS9wb2x5cy9tYXRyaWNlcy90ZXN0cy90ZXN0X25vcm1hbGZvcm1zLnB5Ci0tLSBhL3N5bXB5L3BvbHlzL21hdHJpY2VzL3Rlc3RzL3Rlc3Rfbm9ybWFsZm9ybXMucHkKKysrIGIvc3ltcHkvcG9seXMvbWF0cmljZXMvdGVzdHMvdGVzdF9ub3JtYWxmb3Jtcy5weQpAQCAtNjIsNyArNjIsNyBAQCBkZWYgdGVzdF9oZXJtaXRlX25vcm1hbCgpOgogICAgIGFzc2VydCBoZXJtaXRlX25vcm1hbF9mb3JtKG0pID09IGhuZgogCiAgICAgbSA9IERNKFtbMiwgN10sIFswLCAwXSwgWzAsIDBdXSwgWlopCi0gICAgaG5mID0gRE0oW1tdLCBbXSwgW11dLCBaWikKKyAgICBobmYgPSBETShbWzFdLCBbMF0sIFswXV0sIFpaKQogICAgIGFzc2VydCBoZXJtaXRlX25vcm1hbF9mb3JtKG0pID09IGhuZgogCiAgICAgbSA9IERNKFtbLTIsIDFdLCBbMCwgMV1dLCBaWikK"

_TESTS = json.loads(r"""{"F2P": ["test_hermite_normal"], "P2P": ["test_smith_normal", "test_smith_normal_deprecated"]}""")

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
