from agent.budget import Budget, LoopDetector


def test_budget_ok_checks_steps_tokens_and_time():
    now = [100.0]
    budget = Budget(max_steps=2, max_tokens=10, max_wallclock_s=5, clock=lambda: now[0])
    assert budget.ok()
    budget.tick(4)
    budget.tick(5)
    assert not budget.ok()
    budget = Budget(max_steps=5, max_tokens=10, max_wallclock_s=5, clock=lambda: now[0])
    now[0] = 106.0
    assert not budget.ok()


def test_loop_detector_flags_repeated_actions():
    detector = LoopDetector(threshold=3)
    action = {"tool": "read_file", "args": {"path": "a.py"}}
    assert detector.is_repeating(action) is False
    assert detector.is_repeating(action) is False
    assert detector.is_repeating(action) is True
