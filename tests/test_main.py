from pathlib import Path
from main import main


def test_main_runs_with_fake_llm(tmp_path: Path):
    repo = tmp_path / "repo"; repo.mkdir(); (repo / "a.py").write_text("hello\n", encoding="utf-8")
    code = main(["change hello", str(repo), "--fake"])
    assert code == 0
    assert (repo / "trace.jsonl").exists()
