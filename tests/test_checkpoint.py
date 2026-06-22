from pathlib import Path
from agent.checkpoint import GitCheckpoint


def test_checkpoint_init_diff_and_rollback(tmp_path: Path):
    (tmp_path / "a.txt").write_text("base\n", encoding="utf-8")
    checkpoint = GitCheckpoint(tmp_path)
    checkpoint.init()
    assert checkpoint.diff() == ""
    (tmp_path / "a.txt").write_text("changed\n", encoding="utf-8")
    assert "changed" in checkpoint.diff()
    checkpoint.rollback()
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "base\n"
