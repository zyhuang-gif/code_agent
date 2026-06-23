import subprocess
import sys

raise SystemExit(subprocess.run([sys.executable, "-m", "pytest", "-q"]).returncode)
