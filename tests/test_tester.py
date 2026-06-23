from pathlib import Path

from agent.profile import ProjectProfile
from agent.tester import run_tests


def test_run_tests_returns_passed_result_for_zero_exit(tmp_path: Path):
    calls = []

    def fake_runner(cmd, cwd=None, timeout=None, allow_network=False):
        calls.append((cmd, cwd, timeout, allow_network))
        return {"exit_code": 0, "stdout": "ok\n", "stderr": ""}

    result = run_tests(tmp_path, ProjectProfile(test_cmd="pytest -q"), fake_runner)

    assert result is not None
    assert result.passed is True
    assert result.exit_code == 0
    assert result.output == "ok\n"
    assert calls == [("pytest -q", tmp_path, 60, False)]


def test_run_tests_returns_failing_result_for_nonzero_exit(tmp_path: Path):
    def fake_runner(cmd, cwd=None, timeout=None, allow_network=False):
        return {"exit_code": 1, "stdout": "failed\n", "stderr": "details\n"}

    result = run_tests(tmp_path, ProjectProfile(test_cmd="pytest -q"), fake_runner)

    assert result is not None
    assert result.passed is False
    assert result.exit_code == 1
    assert result.output == "failed\ndetails\n"


def test_run_tests_skips_profiles_without_test_cmd(tmp_path: Path):
    def fake_runner(cmd, cwd=None, timeout=None, allow_network=False):
        raise AssertionError("runner should not be called")

    assert run_tests(tmp_path, ProjectProfile(), fake_runner) is None


def test_run_tests_truncates_combined_output(tmp_path: Path):
    def fake_runner(cmd, cwd=None, timeout=None, allow_network=False):
        return {"exit_code": 1, "stdout": "a" * 2500, "stderr": "b" * 2500}

    result = run_tests(tmp_path, ProjectProfile(test_cmd="pytest -q"), fake_runner)

    assert result is not None
    assert "...<truncated>..." in result.output
    assert len(result.output) < 5000
