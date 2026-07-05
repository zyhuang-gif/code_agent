"""Repair memory — extract, persist, and match historical CMake fix cases."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.fix_report import FixReport

SCHEMA_VERSION = 1
DIFF_EXCERPT_MAX_BYTES = 2000


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
