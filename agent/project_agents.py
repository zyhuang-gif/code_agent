"""Generate a readable AGENTS.generated.md for a repository.

The file contains Project Context, Build And Test, CMake Context, Repair Memory,
and Agent Instructions sections.  It is meant for human/code-review consumption
and never overwrites the manually curated AGENTS.md.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from agent.cmake_context import scan_cmake_context, render_cmake_context
from agent.profile import load_profile
from agent.repair_memory import load_repair_memory, repair_memory_jsonl


def _read_if_exists(path: Path) -> str | None:
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def _render_repair_memory_section(memory_path: Path) -> str:
    cases = load_repair_memory(memory_path)
    if not cases:
        return "- No repair memory recorded yet.\n"

    lines = [f"- {len(cases)} repair case(s) recorded:", ""]
    for case in cases:
        lines.append(f"  - [{case.case_id}] {case.error_type}: {case.root_cause or 'no root cause'} "
                     f"(status={case.verification_status}, source={case.source})")
    lines.append("")
    return "\n".join(lines)


def generate_agents_md(
    repo: Path,
    profile_path: Path | None = None,
) -> str:
    """Generate the full AGENTS.generated.md text.

    Parameters
    ----------
    repo:
        Root of the target repository.
    profile_path:
        Path to the project profile YAML (optional — uses default profile if omitted).
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    profile = load_profile(profile_path) if profile_path else None
    context = scan_cmake_context(repo, profile) if profile else None
    readme = _read_if_exists(repo / "README.md")
    memory_path = repair_memory_jsonl(repo)

    lines = [
        f"# {repo.name} — Project Agent Context",
        "",
        f"> Auto-generated {now}.  Do not edit manually — use `python -m agent.project_agents` to regenerate.",
        "",
    ]

    # --- Project Context ---
    lines.extend([
        "## Project Context",
        "",
    ])
    if readme:
        lines.append(f"{readme[:3000]}")
    else:
        lines.append(f"- Repository root: `{repo}`")
        lines.append("- No README.md found.")
    lines.append("")

    # --- Build And Test ---
    lines.extend([
        "## Build And Test",
        "",
    ])
    if profile and profile.test_cmd:
        lines.append(f"- Test command: `{profile.test_cmd}`")
    if profile and profile.setup_cmd:
        lines.append(f"- Setup command: `{profile.setup_cmd}`")
    if profile and profile.language:
        lines.append(f"- Language: `{profile.language}`")
    lines.append("")

    # --- CMake Context ---
    lines.append("## CMake Context")
    lines.append("")
    if context:
        lines.append(render_cmake_context(context))
    else:
        lines.append("- No CMake context available.")
    lines.append("")

    # --- Repair Memory ---
    lines.extend([
        "## Repair Memory",
        "",
    ])
    lines.append(_render_repair_memory_section(memory_path))

    # --- Agent Instructions ---
    lines.extend([
        "## Agent Instructions",
        "",
        "- Prefer target-based CMake fixes (`target_include_directories`, `target_link_libraries`).",
        "- Make the smallest diff that passes verification — each change must serve the build.",
        "- Re-run the configured CMake command with `run_command` before `finish`.",
        "- Do not install packages or fetch from the network.",
        "- Before editing a CMake file, inspect related source files and headers.",
        "- When a repair memory case matches the current error, review its diff excerpt first.",
        "",
    ])

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate AGENTS.generated.md for a repository."
    )
    parser.add_argument("repo", type=Path, help="Path to the repository root")
    parser.add_argument("--profile", type=Path, default=None, help="Path to profile YAML")
    parser.add_argument("--output", type=Path, default=None, help="Output file path (default: <repo>/AGENTS.generated.md)")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    output = (args.output or repo / "AGENTS.generated.md").resolve()
    # 安全阀：不覆盖 AGENTS.md
    if output.name == "AGENTS.md":
        print("Error: refusing to overwrite AGENTS.md. Use --output to specify a different path.", file=__import__("sys").stderr)
        return 1

    content = generate_agents_md(repo, args.profile)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    print(f"Written: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
