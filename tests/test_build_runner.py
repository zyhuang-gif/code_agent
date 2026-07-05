import json
from pathlib import Path

from agent.build_runner import run_cmake_verification, split_cmake_test_command
from agent.profile import ProjectProfile
from agent.trace import Trace


def test_split_cmake_test_command_labels_phases():
    profile = ProjectProfile(
        language="cmake",
        test_cmd='cmake -S . -B build -G "MinGW Makefiles" && cmake --build build && ctest --test-dir build --output-on-failure',
    )

    phases = split_cmake_test_command(profile)

    assert phases == [
        ("configure", 'cmake -S . -B build -G "MinGW Makefiles"'),
        ("build", "cmake --build build"),
        ("test", "ctest --test-dir build --output-on-failure"),
    ]


def test_run_cmake_verification_stops_after_failure_and_records_trace(tmp_path: Path):
    calls = []

    def runner(cmd, cwd=None, timeout=None, allow_network=False):
        calls.append((cmd, cwd, timeout, allow_network))
        return {"exit_code": 1, "stdout": "fatal error: x.hpp: No such file or directory\n", "stderr": ""}

    profile = ProjectProfile(language="cmake", test_cmd="cmake -S . -B build && cmake --build build", test_timeout=12)
    trace = Trace(tmp_path / "trace.jsonl")

    attempts = run_cmake_verification(tmp_path, profile, runner, trace)

    assert len(attempts) == 1
    assert attempts[0].phase == "configure"
    assert attempts[0].exit_code == 1
    assert calls == [("cmake -S . -B build", tmp_path, 12, False)]
    rows = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text(encoding="utf-8-sig").splitlines()]
    assert rows[-1]["t"] == "build_attempt"
    assert rows[-1]["phase"] == "configure"


def test_summarize_cmake_attempts_reports_first_failure():
    from agent.build_runner import BuildAttempt, summarize_cmake_attempts

    attempts = [
        BuildAttempt("cmake -S . -B build", "configure", 0, "configured"),
        BuildAttempt("cmake --build build", "build", 1, "fatal error: x.hpp: No such file or directory"),
    ]

    summary = summarize_cmake_attempts(attempts)

    assert summary["status"] == "failed"
    assert summary["first_failure"]["phase"] == "build"
    assert summary["first_failure"]["exit_code"] == 1
    assert summary["combined_output"] == "configured\nfatal error: x.hpp: No such file or directory"
