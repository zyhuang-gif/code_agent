"""Repair memory — extract, persist, and match historical CMake fix cases."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.build_errors import BuildErrorSummary
from agent.fix_report import FixReport

SCHEMA_VERSION = 1
DIFF_EXCERPT_MAX_BYTES = 2000
MAX_MATCHES_DEFAULT = 3


@dataclass(frozen=True)
class RepairMemoryCase:
    case_id: str
    schema_version: int
    task: str
    error_type: str
    root_cause: str
    edited_files: list[str]
    verification_status: str
    verification_commands: list[str]
    initial_phase: str
    final_phase: str
    evidence: list[str]
    diff_excerpt: str
    source: str


@dataclass(frozen=True)
class RepairMemoryMatch:
    case: RepairMemoryCase
    score: float


def repair_memory_jsonl(repo: Path) -> Path:
    return repo / "repair_memory.jsonl"


def _make_case_id(error_type: str, edited_files: list[str], task: str) -> str:
    """Deterministic case_id from error_type, edited_files, and task."""
    key = f"{error_type}|{','.join(sorted(edited_files))}|{task}"
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def load_repair_memory(path: Path) -> list[RepairMemoryCase]:
    """Load repair memory cases from a JSONL file.

    Returns an empty list if the file does not exist.  Malformed lines are
    silently skipped.
    """
    if not path.exists():
        return []
    cases: list[RepairMemoryCase] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            cases.append(_case_from_dict(data))
    return cases


def append_repair_case(path: Path, case: RepairMemoryCase) -> None:
    """Append a repair case to the JSONL file, deduping by case_id.

    If a case with the same case_id already exists in the file, the new case
    is silently skipped.
    """
    existing_ids = {existing.case_id for existing in load_repair_memory(path)}
    if case.case_id in existing_ids:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_case_to_dict(case), ensure_ascii=False) + "\n")


def extract_repair_case(
    report: FixReport,
    diff: str,
    source: str,
) -> RepairMemoryCase:
    """Extract a RepairMemoryCase from a FixReport and related artifacts."""
    diff_excerpt = diff[:DIFF_EXCERPT_MAX_BYTES] if diff else ""
    case_id = _make_case_id(report.error_type, report.edited_files, report.task)
    return RepairMemoryCase(
        case_id=case_id,
        schema_version=SCHEMA_VERSION,
        task=report.task,
        error_type=report.error_type,
        root_cause=report.root_cause,
        edited_files=report.edited_files,
        verification_status=report.verification_status,
        verification_commands=report.commands,
        initial_phase=report.initial_phase or "",
        final_phase=report.final_phase or "",
        evidence=report.initial_evidence,
        diff_excerpt=diff_excerpt,
        source=source,
    )


def _case_to_dict(case: RepairMemoryCase) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "schema_version": case.schema_version,
        "task": case.task,
        "error_type": case.error_type,
        "root_cause": case.root_cause,
        "edited_files": case.edited_files,
        "verification_status": case.verification_status,
        "verification_commands": case.verification_commands,
        "initial_phase": case.initial_phase,
        "final_phase": case.final_phase,
        "evidence": case.evidence,
        "diff_excerpt": case.diff_excerpt,
        "source": case.source,
    }


def _case_from_dict(data: dict[str, Any]) -> RepairMemoryCase:
    return RepairMemoryCase(
        case_id=data.get("case_id", ""),
        schema_version=data.get("schema_version", SCHEMA_VERSION),
        task=data.get("task", ""),
        error_type=data.get("error_type", "unknown"),
        root_cause=data.get("root_cause", ""),
        edited_files=data.get("edited_files", []),
        verification_status=data.get("verification_status", "not_run"),
        verification_commands=data.get("verification_commands", []),
        initial_phase=data.get("initial_phase", ""),
        final_phase=data.get("final_phase", ""),
        evidence=data.get("evidence", []),
        diff_excerpt=data.get("diff_excerpt", ""),
        source=data.get("source", ""),
    )


# ---------------------------------------------------------------------------
#  Matching — pure local scoring, no vector DB / embeddings / network
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> set[str]:
    """Split text into lowercase alphanumeric tokens."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _score_match(case: RepairMemoryCase, error: BuildErrorSummary) -> float:
    """Score how relevant *case* is to the current *error*.

    Scoring dimensions (weighted):
    - exact error_type match: 40
    - keyword overlap between evidence + root_cause: up to 30
    - edited file overlap: up to 20
    - initial_phase match: 10
    """
    score = 0.0

    # Exact error_type
    if case.error_type == error.error_type:
        score += 40.0

    # Keyword overlap — tokens from evidence, root_cause, and the summary's
    # structured fields
    error_tokens: set[str] = set()
    for line in error.evidence_lines:
        error_tokens |= _tokenize(line)
    error_tokens |= _tokenize(error.message)
    if error.missing_header:
        error_tokens |= _tokenize(error.missing_header)
    if error.missing_symbol:
        error_tokens |= _tokenize(error.missing_symbol)
    if error.missing_package:
        error_tokens |= _tokenize(error.missing_package)
    if error.missing_target:
        error_tokens |= _tokenize(error.missing_target)

    case_tokens: set[str] = set()
    for line in case.evidence:
        case_tokens |= _tokenize(line)
    case_tokens |= _tokenize(case.root_cause)
    case_tokens |= _tokenize(" ".join(case.edited_files))

    if error_tokens and case_tokens:
        overlap = len(error_tokens & case_tokens)
        union = len(error_tokens | case_tokens)
        if union > 0:
            score += 30.0 * (overlap / union)

    # Edited file overlap
    if case.edited_files:
        error_files = set(error.suggested_files or [])
        if error_files:
            file_overlap = len(set(case.edited_files) & error_files) / len(error_files)
            score += 20.0 * file_overlap

    # Phase match
    if case.initial_phase and error.phase and case.initial_phase == error.phase:
        score += 10.0

    return score


def match_repair_memory(
    memory: list[RepairMemoryCase],
    error: BuildErrorSummary,
    max_matches: int = MAX_MATCHES_DEFAULT,
    min_score: float = 5.0,
) -> list[RepairMemoryMatch]:
    """Find the top-K matching repair cases for a given build error.

    Only returns passed cases (verification_status == "passed") and requires a
    minimum score threshold.
    """
    scored: list[RepairMemoryMatch] = []
    for case in memory:
        if case.verification_status != "passed":
            continue
        score = _score_match(case, error)
        if score >= min_score:
            scored.append(RepairMemoryMatch(case=case, score=score))
    scored.sort(key=lambda m: m.score, reverse=True)
    return scored[:max_matches]


def render_repair_memory(matches: list[RepairMemoryMatch]) -> str:
    """Render matched cases into a prompt section."""
    if not matches:
        return ""

    lines = [
        "Relevant repair memory:",
        "",
    ]
    for i, match in enumerate(matches, start=1):
        case = match.case
        lines.append(f"## Case {i} (id: {case.case_id}, score: {match.score:.1f})")
        lines.append(f"- Error type: {case.error_type}")
        lines.append(f"- Root cause: {case.root_cause or 'not recorded'}")
        lines.append(f"- Fix: {', '.join(case.edited_files) if case.edited_files else 'none'}")
        lines.append(f"- Verification: {case.verification_status}")
        if case.verification_commands:
            lines.append(f"- Verify command: {case.verification_commands[0]}")
        if case.evidence:
            lines.append("- Evidence:")
            for line in case.evidence[:3]:
                lines.append(f"  - {line}")
        if case.diff_excerpt:
            lines.append("- Diff excerpt:")
            for line in case.diff_excerpt.splitlines()[:5]:
                lines.append(f"  {line}")
        lines.append(f"- Source: {case.source}")
        lines.append("")
    return "\n".join(lines)


def select_cmake_repair_memory(
    repo: Path,
    error: BuildErrorSummary,
    max_matches: int = MAX_MATCHES_DEFAULT,
) -> list[RepairMemoryMatch]:
    """Load repair memory from *repo* and return top matches for *error*.

    This is the single convenience entry-point used by main.py and the eval
    harness.  Returns an empty list when the JSONL file is missing or the
    profile does not enable repair memory.
    """
    path = repair_memory_jsonl(repo)
    memory = load_repair_memory(path)
    return match_repair_memory(memory, error, max_matches=max_matches)
