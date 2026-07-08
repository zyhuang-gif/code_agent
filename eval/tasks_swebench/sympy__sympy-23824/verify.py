import base64
import json
import pathlib
import subprocess
import sys

GOLDEN_PATCH_B64 = "ZGlmZiAtLWdpdCBhL3N5bXB5L3BoeXNpY3MvaGVwL3Rlc3RzL3Rlc3RfZ2FtbWFfbWF0cmljZXMucHkgYi9zeW1weS9waHlzaWNzL2hlcC90ZXN0cy90ZXN0X2dhbW1hX21hdHJpY2VzLnB5Ci0tLSBhL3N5bXB5L3BoeXNpY3MvaGVwL3Rlc3RzL3Rlc3RfZ2FtbWFfbWF0cmljZXMucHkKKysrIGIvc3ltcHkvcGh5c2ljcy9oZXAvdGVzdHMvdGVzdF9nYW1tYV9tYXRyaWNlcy5weQpAQCAtMjU3LDEwICsyNTcsMTIgQEAgZGVmIHRlc3Rfa2FoYW5lX3NpbXBsaWZ5MSgpOgogICAgIHQgPSAoRyhtdSkqRyhudSkqRyhyaG8pKkcoc2lnbWEpKkcoLW11KSkKICAgICByID0ga2FoYW5lX3NpbXBsaWZ5KHQpCiAgICAgYXNzZXJ0IHIuZXF1YWxzKC0yKkcoc2lnbWEpKkcocmhvKSpHKG51KSkKLSAgICB0ID0gKEcobXUpKkcobnUpKkcocmhvKSpHKHNpZ21hKSpHKC1tdSkpCisgICAgdCA9IChHKG11KSpHKC1tdSkqRyhyaG8pKkcoc2lnbWEpKQogICAgIHIgPSBrYWhhbmVfc2ltcGxpZnkodCkKLSAgICBhc3NlcnQgci5lcXVhbHMoLTIqRyhzaWdtYSkqRyhyaG8pKkcobnUpKQotCisgICAgYXNzZXJ0IHIuZXF1YWxzKDQqRyhyaG8pKkcoc2lnbWEpKQorICAgIHQgPSAoRyhyaG8pKkcoc2lnbWEpKkcobXUpKkcoLW11KSkKKyAgICByID0ga2FoYW5lX3NpbXBsaWZ5KHQpCisgICAgYXNzZXJ0IHIuZXF1YWxzKDQqRyhyaG8pKkcoc2lnbWEpKQogCiBkZWYgdGVzdF9nYW1tYV9tYXRyaXhfY2xhc3MoKToKICAgICBpLCBqLCBrID0gdGVuc29yX2luZGljZXMoJ2ksaixrJywgTG9yZW50ekluZGV4KQo="

_TESTS = json.loads(r"""{"F2P": ["sympy/physics/hep/tests/test_gamma_matrices.py::test_kahane_simplify1"], "P2P": ["sympy/physics/hep/tests/test_gamma_matrices.py::test_kahane_algorithm", "sympy/physics/hep/tests/test_gamma_matrices.py::test_gamma_matrix_class"]}""")

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
