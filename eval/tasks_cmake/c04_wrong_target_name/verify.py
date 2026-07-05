import subprocess
import sys

commands = [
    ['cmake', '-S', '.', '-B', 'build', '-G', 'MinGW Makefiles'],
    ['cmake', '--build', 'build'],
    ['ctest', '--test-dir', 'build', '--output-on-failure'],
]

for command in commands:
    proc = subprocess.run(command, text=True, capture_output=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr)
        sys.exit(proc.returncode)
