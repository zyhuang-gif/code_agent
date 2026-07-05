"""AgentSpec A/B/C evaluation runner.

This module reuses eval.run_eval and only adds treatment orchestration.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path


PROMPT_INJECTION = "There is an AGENTS.md at repo root. Read it before you start."


@dataclass(frozen=True)
class SpecVariant:
    name: str
    requires_agentspec: bool
    minimal: bool = False


VARIANTS: dict[str, SpecVariant] = {
    "baseline": SpecVariant("baseline", requires_agentspec=False),
    "agentspec-minimal": SpecVariant("agentspec-minimal", requires_agentspec=True, minimal=True),
    "agentspec-full": SpecVariant("agentspec-full", requires_agentspec=True, minimal=False),
}


MANAGED_BLOCK_RE = re.compile(
    r'<!-- agentspec:managed name="(?P<name>[^"]+)" -->.*?'
    r'<!-- agentspec:end name="(?P=name)" -->',
    re.DOTALL,
)


def build_agentspec_command(work_root: Path, agentspec_project: Path) -> list[str]:
    return [
        "uv",
        "run",
        "--project",
        str(agentspec_project),
        "agentspec",
        "scan",
        str(work_root),
        "--write",
        "--force",
        "--no-llm",
    ]


def render_minimal_agents_md(full_text: str) -> str:
    blocks = {match.group("name"): match.group(0).strip() for match in MANAGED_BLOCK_RE.finditer(full_text)}
    required = ["commands", "safety"]
    if any(name not in blocks for name in required):
        raise ValueError("minimal AGENTS.md requires commands and safety managed blocks")
    return "# AGENTS.md\n\n" + "\n\n".join(blocks[name] for name in required) + "\n"


def cleanup_agentspec_side_outputs(work_root: Path) -> None:
    claude_md = work_root / "CLAUDE.md"
    if claude_md.exists():
        claude_md.unlink()
    agent_dir = work_root / ".agent"
    if agent_dir.exists():
        shutil.rmtree(agent_dir)
