from pathlib import Path
from agent.multi_agent import NoOpCheckpoint


def test_noop_checkpoint_is_inert(tmp_path: Path):
    cp = NoOpCheckpoint(tmp_path)
    cp.init()
    assert cp.diff() == ""
    cp.rollback()
