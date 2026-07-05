import subprocess
from pathlib import Path

root = Path.cwd()
proc = subprocess.run(
    'cmake -S . -B build -G "MinGW Makefiles" && cmake --build build && ctest --test-dir build --output-on-failure',
    cwd=root,
    shell=True,
    text=True,
    capture_output=True,
    timeout=120,
)
raise SystemExit(proc.returncode)
