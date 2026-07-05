"""Tests for eval/tasks_cmake_memory benchmark."""

from pathlib import Path

from eval.run_eval import discover


def test_discovers_memory_eval_tasks():
    tasks = {task.id: task for task in discover(Path("eval/tasks_cmake_memory"))}

    assert "m01_without_memory" in tasks
    assert "m02_with_memory" in tasks
    assert all(task.profile.language == "cmake" for task in tasks.values())


def test_m01_has_no_repair_memory():
    """m01 repo 不应预置 repair_memory.jsonl。"""
    m01_repo = Path("eval/tasks_cmake_memory/m01_without_memory/repo")
    assert not (m01_repo / "repair_memory.jsonl").exists()


def test_m02_has_repair_memory():
    """m02 repo 预置 repair_memory.jsonl。"""
    m02_repo = Path("eval/tasks_cmake_memory/m02_with_memory/repo")
    assert (m02_repo / "repair_memory.jsonl").exists()


def test_m02_repair_memory_has_seed_case():
    """m02 的 repair_memory.jsonl 应包含 seed case。"""
    import json
    m02_repo = Path("eval/tasks_cmake_memory/m02_with_memory/repo")
    content = (m02_repo / "repair_memory.jsonl").read_text(encoding="utf-8")
    case = json.loads(content.strip())
    assert case["case_id"] == "abc12345"
    assert case["error_type"] == "missing_header"
    assert case["verification_status"] == "passed"


def test_memory_tasks_have_cmake_profile():
    tasks = discover(Path("eval/tasks_cmake_memory"))
    for task in tasks:
        assert task.profile.language == "cmake"
        assert "cmake" in task.profile.test_cmd


def test_memory_tasks_have_prompt_and_verify():
    for name in ("m01_without_memory", "m02_with_memory"):
        task_dir = Path(f"eval/tasks_cmake_memory/{name}")
        assert (task_dir / "prompt.md").exists()
        assert (task_dir / "verify.py").exists()
        assert (task_dir / "profile.yaml").exists()
        assert (task_dir / "repo" / "CMakeLists.txt").exists()
