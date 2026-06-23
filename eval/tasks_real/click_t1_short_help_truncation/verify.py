import subprocess
import sys

cmd = [sys.executable, "-m", "pytest", "tests/test_utils.py::test_make_default_short_help", "-q", "-p", "no:cacheprovider"]
proc = subprocess.run(cmd, text=True, capture_output=True, timeout=300)
print(proc.stdout, end="")
print(proc.stderr, end="")
raise SystemExit(proc.returncode)
