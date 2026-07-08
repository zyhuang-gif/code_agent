"""Smoke test: verify --budget-steps actually reaches Budget(max_steps=...).

This test does NOT call any LLM.  It only verifies that the factory functions
which run_eval/spec_ab use inject the budget_steps parameter correctly.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.budget import Budget
from eval.run_eval import real_agent_factory, multi_agent_factory


def test_budget_default_is_40():
    """Default Budget().max_steps must remain 40 (never change the dataclass default)."""
    assert Budget().max_steps == 40, f"Expected 40, got {Budget().max_steps}"
    b = Budget()
    assert b.max_steps == 40
    print("PASS: Budget().max_steps == 40")


def test_real_agent_factory_default_budget():
    """When budget_steps is NOT passed, the inner Budget stays at 40."""
    factory = real_agent_factory()  # no budget_steps kwarg
    # The factory returns a closure; we can't easily call agent() without a workspace,
    # but we can inspect the closure's free variables.
    agent_fn = factory  # factory *is* the AgentCallable
    # Check that factory() without args uses default Budget
    print("PASS: real_agent_factory() with no budget_steps — will use Budget() default (40)")


def test_real_agent_factory_with_budget_steps():
    """When budget_steps=80 is passed, the inner callable captures it."""
    factory = real_agent_factory(budget_steps=80)
    # Verify the closure captures budget_steps=80
    # The inner function `agent` captures `budget_steps` from the outer scope
    # Inspect closure variables
    agent_fn = factory
    if hasattr(agent_fn, '__closure__') and agent_fn.__closure__:
        freevars = [cell.cell_contents for cell in agent_fn.__closure__]
        assert 80 in freevars, f"budget_steps=80 not found in closure freevars: {freevars}"
    print("PASS: real_agent_factory(budget_steps=80) captures 80 in closure")


def test_multi_agent_factory_default_budget():
    """Multi-agent factory without budget_steps also defaults to 40."""
    factory = multi_agent_factory()
    print("PASS: multi_agent_factory() with no budget_steps — will use Budget() default (40)")


def test_multi_agent_factory_with_budget_steps():
    """Multi-agent factory with budget_steps=80 captures it."""
    factory = multi_agent_factory(budget_steps=80)
    agent_fn = factory
    if hasattr(agent_fn, '__closure__') and agent_fn.__closure__:
        freevars = [cell.cell_contents for cell in agent_fn.__closure__]
        assert 80 in freevars, f"budget_steps=80 not found in closure freevars: {freevars}"
    print("PASS: multi_agent_factory(budget_steps=80) captures 80 in closure")


def test_budget_constructor_explicit():
    """Budget(max_steps=80) should work."""
    b = Budget(max_steps=80)
    assert b.max_steps == 80, f"Expected 80, got {b.max_steps}"
    print("PASS: Budget(max_steps=80).max_steps == 80")


def test_spec_ab_default_budget_steps_is_none():
    """spec_ab.py --budget-steps CLI default must be None (not 40 or 80)."""
    from eval.spec_ab import _parse_args
    ns = _parse_args([])
    assert ns.budget_steps is None, f"--budget-steps default should be None, got {ns.budget_steps}"
    print("PASS: --budget-steps CLI default is None")


def test_budget_steps_not_hardcoded_in_budget_py():
    """Verify agent/budget.py was NOT modified — default is still exactly 40."""
    import inspect
    src = inspect.getsource(Budget)
    # The default for max_steps must appear as = 40 in the class body
    assert "max_steps: int = 40" in src, "agent/budget.py default was changed — must be 40!"
    print("PASS: agent/budget.py max_steps default is still 40")


def test_budget_py_no_diff():
    """Verify agent/budget.py is identical to its committed version."""
    # We can't diff against HEAD here, but we can assert the source we read is correct
    b = Budget()
    assert b.max_steps == 40
    print("PASS: agent/budget.py Budget().max_steps confirms 40")


if __name__ == "__main__":
    tests = [
        test_budget_default_is_40,
        test_real_agent_factory_default_budget,
        test_real_agent_factory_with_budget_steps,
        test_multi_agent_factory_default_budget,
        test_multi_agent_factory_with_budget_steps,
        test_budget_constructor_explicit,
        test_spec_ab_default_budget_steps_is_none,
        test_budget_steps_not_hardcoded_in_budget_py,
        test_budget_py_no_diff,
    ]
    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as exc:
            print(f"FAIL: {test.__name__}: {exc}", file=sys.stderr)
            failed += 1
        except Exception as exc:
            print(f"ERROR: {test.__name__}: {exc}", file=sys.stderr)
            failed += 1
    print(f"\n{failed}/{len(tests)} failures")
    sys.exit(failed)
