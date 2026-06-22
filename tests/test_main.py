from pathlib import Path
import subprocess

from main import main


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def _init_user_repo(repo: Path) -> None:
    repo.mkdir()
    (repo / "a.py").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "add", "a.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, check=True, capture_output=True, text=True)


def test_main_runs_with_fake_llm_in_isolated_workspace(tmp_path: Path, monkeypatch):
    user_repo = tmp_path / "user-repo"
    _init_user_repo(user_repo)
    before_files = sorted(p.relative_to(user_repo).as_posix() for p in user_repo.rglob("*") if ".git" not in p.parts)
    before_head = _git(user_repo, "rev-parse", "HEAD")
    before_status = _git(user_repo, "status", "--short")
    monkeypatch.chdir(tmp_path)

    code = main(["change hello", str(user_repo), "--fake"])

    after_files = sorted(p.relative_to(user_repo).as_posix() for p in user_repo.rglob("*") if ".git" not in p.parts)
    assert code == 0
    assert after_files == before_files
    assert _git(user_repo, "rev-parse", "HEAD") == before_head
    assert _git(user_repo, "status", "--short") == before_status
    assert not (user_repo / "trace.jsonl").exists()
    assert not (user_repo / "final.diff").exists()
    runs = list((tmp_path / "workspace").glob("run-*"))
    assert len(runs) == 1
    assert (runs[0] / "trace.jsonl").exists()
    assert (runs[0] / "final.diff").exists()
    assert (runs[0] / ".git").exists()


