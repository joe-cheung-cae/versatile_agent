#!/usr/bin/env python3
"""Offline structural validation for the distributable bundle.

The Skill checks below intentionally validate only a registered canonical
contract and an enumerated set of stale literals.  They do not classify
arbitrary English or attempt to render CommonMark.  Markdown checks use the
small, source-level dialect documented by the Skill.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path


REQUIRED_AGENT_KEYS = {
    "name",
    "description",
    "developer_instructions",
    "model",
    "model_reasoning_effort",
    "sandbox_mode",
}
ALLOWED_MODELS = {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}
ALLOWED_EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}
ALLOWED_SANDBOX = {"read-only", "workspace-write", "danger-full-access"}
EXPECTED_COMMON = {
    "code_mapper",
    "architect",
    "implementer",
    "tester",
    "test_validator",
    "reviewer",
    "gpu_reviewer",
    "numerics_reviewer",
    "parallelism_reviewer",
    "performance_profiler",
    "security_reviewer",
    "docs_researcher_luna",
    "docs_researcher_terra",
}
EXPECTED_COMMON_FILES = {f"{name}.toml" for name in EXPECTED_COMMON}
RUNTIME_RECORD_FIXTURES = {
    "app-task.json",
    "cli-and-app-records.json",
    "app-task-provenance-on-native.json",
    "native-route-mismatch.json",
    "native-provenance-on-app-task.json",
    "disguised-composite.json",
    "duplicate-runtime-id.json",
    "document-schema-bool.json",
    "generation-list.json",
    "mismatched-provenance.json",
    "missing-field.json",
    "mixed-evidence.json",
    "native-effective-unknown.json",
    "native-effective-support-conflict.json",
    "native-partial-effective-mismatch.json",
    "native-observed-null.json",
    "native-padded-effective.json",
    "native-request-only.json",
    "native-spawn.json",
    "native-whitespace-effective.json",
    "native-assertion-list.json",
    "native-assertion-primitive.json",
    "record-schema-float.json",
    "unknown-fact.json",
    "unknown-model-known-effort.json",
    "app-luna-only.sh",
    "app-v1-luna.sh",
    "cli-v1-luna.sh",
    "cli-v2-luna.sh",
    "cli-v2-no-luna.sh",
}
ROUTING_FIXTURES = {
    "luna-routing-rejection.json",
    "luna-mismatch.json",
    "luna-success.json",
    "terra-success.json",
}
SKILL_REFERENCE_FILES = {
    "workflow.md",
    "task-contract.md",
    "review-policy.md",
    "cuda-cae-review-policy.md",
    "model-routing.md",
}
EXPECTED_DESCRIPTION = (
    "Use for non-trivial repository engineering needing mapping, planning, implementation, "
    "tests, independent review, acceptance, or targeted CUDA/HPC/numerical/security specialists. "
    "Do not use for simple Q&A or status-only work. Probes and App tasks are not native effective "
    "evidence; this Skill does not change the parent model or permissions, guarantee model "
    "availability, or perform automatic CLI model switching or fallback."
)
EXPECTED_UI = {
    "display_name": "Versatile Development",
    "short_description": "Classify, route, verify, and review engineering work",
    "default_prompt": "Use $versatile-dev for non-trivial repository engineering: classify the task, plan, implement, verify, independently review, and accept the change.",
}
DIRECT_LINK_LINES = {
    "references/model-routing.md": "[model routing](references/model-routing.md)",
    "references/task-contract.md": "[task contract](references/task-contract.md)",
    "references/cuda-cae-review-policy.md": "[CUDA and CAE review](references/cuda-cae-review-policy.md)",
    "references/workflow.md": "[workflow](references/workflow.md)",
    "references/review-policy.md": "[review policy](references/review-policy.md)",
}
CANONICAL_BLOCKS = {
    "SKILL.md": (
        "<!-- BEGIN versatile-dev canonical contract -->",
        "<!-- END versatile-dev canonical contract -->",
        (
            "Lead owns user intent, architecture, task state, diff, tests, review triage, and acceptance.",
            "Classify work as Simple (isolated and obvious), Moderate (multi-file, non-obvious, or test-bearing), or Complex (architecture, concurrency, CUDA, numerical, security, interface, or performance-sensitive); reclassify when evidence changes.",
            "Simple obvious changes use direct work; delegate only when delegation is material to correctness, coverage, or throughput.",
            "Native documentation research uses the same-interface PRECHECK; missing, conflicting, or unobservable metadata fails closed, with routing details in the model-routing reference.",
            "Luna is first; only a classified native routing rejection or complete same-attempt native mismatch permits at most one Terra; all other outcomes fail closed.",
            "The App user-visible task lane is separate and requires explicit authorization in the current user request; it never supplies native effective evidence or authorizes Terra fallback.",
            "The task packet has exactly five parts: Objective, Ownership, Inputs/evidence, Constraints/requirements, Verification/handoff.",
            "A dynamic packet names actual files, interfaces, commands, evidence, constraints, and verification.",
            "One writer owns overlapping files; parallel work is limited to disjoint files.",
            "A fresh independent reviewer reviews the completed diff; any correction invalidates the verdict and requires fresh review.",
            "The lead reruns verification and alone accepts completion.",
            "Route gpu_reviewer, numerics_reviewer, parallelism_reviewer, performance_profiler, and security_reviewer only when their boundary is touched; never spawn all specialists by default.",
        ),
    ),
    "model-routing.md": (
        "<!-- BEGIN versatile-dev canonical routing contract -->",
        "<!-- END versatile-dev canonical routing contract -->",
        (
            "Both docs_researcher_luna and docs_researcher_terra are installed and pinned to gpt-5.6-luna/max and gpt-5.6-terra/high.",
            "Both researchers use the same-interface PRECHECK.",
            "route_research.py provides deterministic replay and decision semantics.",
            "Luna is first; only a classified native routing rejection or complete same-attempt native mismatch permits at most one Terra attempt.",
            "A permitted Terra transition is FALLBACK_PENDING and is limited to one Terra attempt.",
            "Content, tool, task, timeout, and unknown failures do not authorize Terra fallback.",
            "Missing, conflicting, or unobservable effective evidence is STOP_UNVERIFIED.",
            "Every attempt carries the same canonical task_packet_hash.",
            "runtime_audit.py is separate from the installation manifest.",
            "Installed, configured, capability, requested, observed, and effective are separate fact layers.",
            "The installation manifest, probe, and App task cannot fill native effective facts.",
            "The App user-visible task lane requires explicit authorization in the current user request and cannot authorize native Terra fallback.",
            "This Skill cannot change the parent model, bypass permissions, guarantee model availability, or perform automatic CLI model switching or fallback.",
            "Offline validation does not prove live runtime conformance.",
        ),
    ),
}
CANONICAL_SECTIONS = {
    "SKILL.md": "## Contract",
    "model-routing.md": "## Canonical routing contract",
}
STALE_LITERALS = (
    "current implementation boundary",
    "installed bundle provides exactly one legacy docs_researcher",
    "dual-agent installer is future work",
    "dual researchers are future work",
    "route helper is future work",
    "automatic cli fallback",
    "probe proves effective route",
    "probe confirms effective native route",
)


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.errors.append(message)


def parse_agent(path: Path, check: Validation) -> dict:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        check.errors.append(f"invalid agent TOML {path}: {exc}")
        return {}
    missing = REQUIRED_AGENT_KEYS - set(data)
    check.require(not missing, f"{path} missing keys: {sorted(missing)}")
    check.require(data.get("model") in ALLOWED_MODELS, f"{path} has unsupported model: {data.get('model')}")
    check.require(data.get("model_reasoning_effort") in ALLOWED_EFFORTS, f"{path} has unsupported effort: {data.get('model_reasoning_effort')}")
    check.require(data.get("sandbox_mode") in ALLOWED_SANDBOX, f"{path} has unsupported sandbox: {data.get('sandbox_mode')}")
    check.require(bool(str(data.get("description", "")).strip()), f"{path} has an empty description")
    check.require(bool(str(data.get("developer_instructions", "")).strip()), f"{path} has empty developer instructions")
    return data


def _frontmatter(text: str) -> tuple[str | None, list[str]]:
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if match is None:
        return None, ["SKILL.md must begin with YAML frontmatter"]
    block = match.group(1)
    expected = f"name: versatile-dev\ndescription: {EXPECTED_DESCRIPTION}"
    if block != expected:
        return block, ["SKILL.md frontmatter must be the exact two-line trigger contract"]
    return block, []


def _fence_start(line: str) -> tuple[str, int] | None:
    backtick = re.fullmatch(r"[ ]{0,3}(`{3,})([^`]*)", line)
    if backtick is not None:
        return "`", len(backtick.group(1))
    tilde = re.fullmatch(r"[ ]{0,3}(~{3,})(.*)", line)
    if tilde is not None:
        return "~", len(tilde.group(1))
    return None


def _fence_close(line: str, fence: tuple[str, int]) -> bool:
    marker, length = fence
    return re.fullmatch(rf"[ ]{{0,3}}{re.escape(marker)}{{{length},}}[ \t]*", line) is not None


def _source_flags(
    text: str,
    marker_lines: set[str] | None = None,
    *,
    mask_inline_code: bool = True,
) -> list[bool]:
    """Mark only unindented, unquoted, unmasked source lines as active."""
    marker_lines = marker_lines or set()
    flags: list[bool] = []
    fence: tuple[str, int] | None = None
    comment = False
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        active = fence is None and not comment
        if fence is not None:
            flags.append(False)
            if _fence_close(line, fence):
                fence = None
            continue
        if line in marker_lines:
            flags.append(active)
            continue
        start = _fence_start(line)
        if start is not None:
            flags.append(False)
            fence = start
            continue
        if "<!--" in line:
            flags.append(False)
            if "-->" not in line[line.index("<!--") + 4 :]:
                comment = True
            continue
        if comment:
            flags.append(False)
            if "-->" in line:
                comment = False
            continue
        container = bool(re.match(r"^(?:[ \t]+|>\s*|(?:[-+*]|\d+\.)\s+)", line))
        inline_code = mask_inline_code and any(
            char == "`"
            and (len(line[:index]) - len(line[:index].rstrip("\\"))) % 2 == 0
            for index, char in enumerate(line)
        )
        flags.append(active and not container and not inline_code)
    return flags


def _source_dialect_violations(filename: str, text: str) -> list[str]:
    """Reject unsupported angle/HTML source; only registered marker lines are allowed."""
    registered = CANONICAL_BLOCKS.get(filename)
    marker_lines = set(registered[:2]) if registered is not None else set()
    errors: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        if line in marker_lines:
            continue
        if "<!--" in line or "-->" in line or re.search(r"<[^>\n]+>", line):
            errors.append(f"{filename}:{number} contains unsupported angle or HTML source syntax")
    fence: tuple[str, int] | None = None
    for number, line in enumerate(text.splitlines(), 1):
        if fence is not None:
            if _fence_close(line, fence):
                fence = None
            elif re.fullmatch(rf"[ ]{{0,3}}{re.escape(fence[0])}{{{fence[1]},}}.*", line):
                errors.append(f"{filename}:{number} contains an invalid fenced close suffix")
        else:
            fence = _fence_start(line)
    if fence is not None:
        errors.append(f"{filename} contains an unclosed fenced source block")
    return errors


def canonical_block_violations(filename: str, text: str) -> list[str]:
    registered = CANONICAL_BLOCKS.get(filename)
    if registered is None:
        return []
    begin, end, expected = registered
    lines = text.splitlines()
    marker_lines = {begin, end}
    flags = _source_flags(text, marker_lines)
    begin_indexes = [i for i, line in enumerate(lines) if line == begin]
    end_indexes = [i for i, line in enumerate(lines) if line == end]
    errors: list[str] = []
    if len(begin_indexes) != 1 or len(end_indexes) != 1:
        return [f"{filename} canonical block markers must occur exactly once"]
    begin_index, end_index = begin_indexes[0], end_indexes[0]
    if begin_index >= end_index or not flags[begin_index] or not flags[end_index]:
        return [f"{filename} canonical block markers must be unindented and unmasked"]
    section = CANONICAL_SECTIONS[filename]
    all_section_indexes = [i for i, line in enumerate(lines) if line == section]
    active_section_indexes = [i for i in all_section_indexes if flags[i]]
    if len(all_section_indexes) != 1 or len(active_section_indexes) != 1:
        return [f"{filename} canonical block requires exactly one active, unmasked {section} section"]
    section_index = active_section_indexes[0]
    if section_index >= begin_index:
        return [f"{filename} canonical block section must precede its begin marker"]
    peer_flags = _source_flags(text, marker_lines, mask_inline_code=False)
    peer_headings = [
        i
        for i, line in enumerate(lines)
        if peer_flags[i] and re.fullmatch(r"#{1,2}(?:$|[ \t]+.*)", line)
    ]
    next_peer = next((i for i in peer_headings if i > section_index), None)
    if next_peer is not None and end_index >= next_peer:
        return [f"{filename} canonical block must end before the next active H1/H2 section"]
    actual = tuple(lines[begin_index + 1 : end_index])
    if actual != expected:
        errors.append(f"{filename} canonical block contents drifted")
    for line in expected:
        if lines.count(line) != 1:
            errors.append(f"{filename} canonical clause must occur exactly once: {line}")
    return errors


def openai_yaml_violations(text: str) -> list[str]:
    """Parse the deliberately closed interface schema, not general YAML."""
    lines = text.splitlines()
    if lines == [""]:
        lines = []
    errors: list[str] = []
    if len(lines) != 4 or lines[0] != "interface:":
        return ["agents/openai.yaml must use the exact four-line interface schema"]
    values: dict[str, str] = {}
    expected_order = ("display_name", "short_description", "default_prompt")
    for line, expected_key in zip(lines[1:], expected_order):
        match = re.fullmatch(r'  ([a-z_]+): ("(?:\\.|[^"\\])*")', line)
        if match is None or match.group(1) != expected_key:
            errors.append(f"agents/openai.yaml has non-canonical interface line: {line!r}")
            continue
        try:
            value = json.loads(match.group(2))
        except json.JSONDecodeError:
            errors.append(f"agents/openai.yaml has malformed JSON string: {line!r}")
            continue
        if not isinstance(value, str):
            errors.append(f"agents/openai.yaml values must be strings: {line!r}")
            continue
        values[expected_key] = value
    if set(values) != set(expected_order):
        errors.append("agents/openai.yaml interface keys must be exactly display_name, short_description, default_prompt")
    for key, expected in EXPECTED_UI.items():
        if values.get(key) != expected:
            errors.append(f"agents/openai.yaml {key} drifted from its canonical value")
    return errors


def _inline_tokens(line: str) -> list[tuple[int, int, str, str]]:
    tokens: list[tuple[int, int, str, str]] = []
    for match in re.finditer(r"(?<!\\)(!?)(\[[^\]\n]*\])\(([^)\n]*)\)", line):
        tokens.append((match.start(), match.end(), match.group(1), match.group(3).strip()))
    return tokens


def _external_or_fragment(target: str) -> bool:
    target = target.strip().strip("<>")
    return target.startswith("#") or bool(re.match(r"(?i)^(?:https?://|mailto:)", target))


def _has_link_syntax_without_token(line: str) -> bool:
    return any(marker in line for marker in ("](", "][", "]:"))


def _reference_file_link_violations(filename: str, text: str) -> list[str]:
    errors: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        for _, _, _, target in _inline_tokens(line):
            if not _external_or_fragment(target):
                errors.append(f"{filename}:{number} contains a cross-file Markdown link")
        if _has_link_syntax_without_token(line) and not _inline_tokens(line):
            errors.append(f"{filename}:{number} contains unsupported link syntax")
        definition = re.match(r"^\s*\[[^\]\n]+\]:\s*(\S+)", line)
        if definition is not None and not _external_or_fragment(definition.group(1)):
            errors.append(f"{filename}:{number} contains a cross-file reference definition")
        for html in re.finditer(
            r"<a\b[^>]*\bhref\s*=\s*(?:([\"'])(.*?)\1|([^\s>]+))",
            line,
            re.IGNORECASE,
        ):
            target = html.group(2) if html.group(1) else html.group(3)
            if target is not None and not _external_or_fragment(target):
                errors.append(f"{filename}:{number} contains a cross-file HTML link")
        if re.search(r"<a\b", line, re.IGNORECASE) and "href" not in line.casefold():
            errors.append(f"{filename}:{number} contains unsupported HTML anchor syntax")
    return errors


def reference_topology_violations(skill_text: str, reference_map: dict[str, str], skill_path: Path | None = None) -> list[str]:
    errors: list[str] = []
    errors.extend(_source_dialect_violations("SKILL.md", skill_text))
    if set(reference_map) != SKILL_REFERENCE_FILES:
        errors.append(f"skill references must be exactly {sorted(SKILL_REFERENCE_FILES)}: {sorted(reference_map)}")

    active = _source_flags(skill_text)
    skill_lines = skill_text.splitlines()
    expected_counts = {target: 0 for target in DIRECT_LINK_LINES}
    for index, line in enumerate(skill_lines):
        exact_target = next((target for target, source in DIRECT_LINK_LINES.items() if line == source), None)
        if exact_target is not None and index < len(active) and active[index]:
            expected_counts[exact_target] += 1
        tokens = _inline_tokens(line)
        if tokens:
            if not (len(tokens) == 1 and exact_target is not None and active[index]):
                errors.append(f"SKILL.md:{index + 1} contains an unsupported non-canonical link")
        elif _has_link_syntax_without_token(line):
            errors.append(f"SKILL.md:{index + 1} contains malformed or multiline link syntax")
        if re.match(r"^\s*\[[^\]\n]+\]:", line) or re.search(r"<a\b|\bhref\s*=", line, re.IGNORECASE):
            errors.append(f"SKILL.md:{index + 1} contains a reference definition or HTML anchor")
        if "references/" in line and line not in DIRECT_LINK_LINES.values():
            errors.append(f"SKILL.md:{index + 1} contains an unsupported reference path")
        if ".md" in line and line not in DIRECT_LINK_LINES.values():
            errors.append(f"SKILL.md:{index + 1} contains an unsupported Markdown path")
    for target, count in expected_counts.items():
        if count != 1:
            errors.append(f"SKILL.md must contain exactly one active direct link to {target}; found {count}")

    for filename, text in reference_map.items():
        errors.extend(_source_dialect_violations(filename, text))
        errors.extend(_reference_file_link_violations(filename, text))
    return errors


def _task_heading(line: str) -> tuple[int, str] | None:
    match = re.fullmatch(r"(#{1,6}) (.+)", line)
    if match is None:
        return None
    return len(match.group(1)), match.group(2)


_ATX_SOURCE_RE = re.compile(
    r"^(?P<prefix>[ \t]*(?:(?:>[ \t]*)|(?:(?:[-+*]|\d{1,9}[.)])[ \t]+))*)"
    r"(?P<marks>#{1,6})(?P<separator>[ \t]+|$)(?P<title>.*)$"
)
_SOURCE_PREFIX_RE = re.compile(
    r"^(?P<prefix>[ \t]*(?:(?:>[ \t]*)|(?:(?:[-+*]|\d{1,9}[.)])[ \t]+))*)"
    r"(?P<content>.*)$"
)


def _source_atx_heading(line: str) -> tuple[str, int, str, str] | None:
    match = _ATX_SOURCE_RE.fullmatch(line)
    if match is None:
        return None
    return (
        match.group("prefix"),
        len(match.group("marks")),
        match.group("separator"),
        match.group("title"),
    )


def _source_prefix_parts(line: str) -> tuple[str, str]:
    match = _SOURCE_PREFIX_RE.fullmatch(line)
    if match is None:
        return "", line
    return match.group("prefix"), match.group("content")


def task_contract_violations(text: str) -> list[str]:
    expected_h1 = "# Subagent task contract"
    expected_h2 = [
        "## 1. Objective",
        "## 2. Ownership",
        "## 3. Inputs/evidence",
        "## 4. Constraints/requirements",
        "## 5. Verification/handoff",
    ]
    lines = text.splitlines()
    errors: list[str] = []
    if any(re.search(r"(?:`{3,}|~{3,})", line) for line in lines):
        errors.append("task-contract.md does not allow fenced code")
    if re.search(r"<h[1-6](?:\s|>)", text, re.IGNORECASE):
        errors.append("task-contract.md does not allow raw HTML headings")
    headings: list[tuple[int, str, int]] = []
    for index, line in enumerate(lines):
        source_heading = _source_atx_heading(line)
        if source_heading is not None:
            prefix, level, separator, title = source_heading
            if prefix or separator != " ":
                errors.append(f"task-contract.md:{index + 1} contains a noncanonical or containerized heading")
            if not prefix:
                headings.append((level, title, index))
    if lines.count(expected_h1) != 1:
        errors.append("task-contract.md must contain exactly one exact H1")
    if any(level == 1 and title != "Subagent task contract" for level, title, _ in headings):
        errors.append("task-contract.md contains an unexpected H1")
    actual_h2 = [f"{'#' * level} {title}" for level, title, _ in headings if level == 2]
    if actual_h2 != expected_h2:
        errors.append("task-contract.md H2 headings must be exactly the five ordered contract sections")
    if any(level != 1 and level != 2 for level, _, _ in headings):
        errors.append("task-contract.md must not contain any H3-H6 heading")
    expected_sequence = [(1, "Subagent task contract")] + [
        (2, heading.removeprefix("## ")) for heading in expected_h2
    ]
    actual_sequence = [(level, title) for level, title, _ in headings]
    if actual_sequence != expected_sequence:
        errors.append("task-contract.md root heading sequence must be the H1 followed by the five ordered H2 sections")
    for index in range(1, len(lines)):
        prefix, content = _source_prefix_parts(lines[index])
        if not re.fullmatch(r"(?:=+|-+)[ \t]*", content):
            continue
        previous_prefix, previous_content = _source_prefix_parts(lines[index - 1])
        if previous_content.strip():
            errors.append(f"task-contract.md:{index + 1} contains a Setext heading")
    return errors


def semantic_contract_violations(skill_text: str, reference_map: dict[str, str], ui_text: str) -> list[str]:
    """Validate the registered canonical clauses, not arbitrary natural language."""
    errors: list[str] = []
    _, frontmatter_errors = _frontmatter(skill_text)
    errors.extend(frontmatter_errors)
    errors.extend(_source_dialect_violations("SKILL.md", skill_text))
    for filename, text in reference_map.items():
        errors.extend(_source_dialect_violations(filename, text))
    errors.extend(canonical_block_violations("SKILL.md", skill_text))
    if "model-routing.md" in reference_map:
        errors.extend(canonical_block_violations("model-routing.md", reference_map["model-routing.md"]))
    errors.extend(openai_yaml_violations(ui_text))
    corpus = "\n".join((skill_text, ui_text, *reference_map.values())).casefold()
    for literal in STALE_LITERALS:
        if literal.casefold() in corpus:
            errors.append(f"stale contract literal is forbidden: {literal}")
    return errors


def validate_skill(root: Path, check: Validation) -> None:
    skill = root / "payload/skills/versatile-dev/SKILL.md"
    check.require(skill.is_file(), f"missing {skill}")
    if not skill.is_file():
        return
    text = skill.read_text(encoding="utf-8")
    reference_dir = root / "payload/skills/versatile-dev/references"
    actual_references = {path.name for path in reference_dir.glob("*.md")}
    reference_map = {
        path.name: path.read_text(encoding="utf-8")
        for path in reference_dir.glob("*.md")
        if path.is_file()
    }
    ui = root / "payload/skills/versatile-dev/agents/openai.yaml"
    check.require(ui.is_file(), "missing agents/openai.yaml")
    ui_text = ui.read_text(encoding="utf-8") if ui.is_file() else ""
    check.require(actual_references == SKILL_REFERENCE_FILES, f"skill references must be exactly {sorted(SKILL_REFERENCE_FILES)}: {sorted(actual_references)}")
    for error in semantic_contract_violations(text, reference_map, ui_text):
        check.errors.append(error)
    for error in task_contract_violations(reference_map.get("task-contract.md", "")):
        check.errors.append(error)
    for error in reference_topology_violations(text, reference_map, skill):
        check.errors.append(error)


def validate_agents(root: Path, check: Validation) -> None:
    for obsolete in (
        root / "payload/agents/profiles/luna-v1/docs_researcher.toml",
        root / "payload/agents/profiles/terra-fallback/docs_researcher.toml",
    ):
        check.require(not obsolete.exists() and not obsolete.is_symlink(), f"obsolete profile payload must be absent: {obsolete}")
    common_dir = root / "payload/agents/common"
    common_paths = sorted(common_dir.glob("*.toml"))
    common_data = {path.name: parse_agent(path, check) for path in common_paths}
    check.require(set(common_data) == EXPECTED_COMMON_FILES, f"common agent files mismatch: {sorted(common_data)}")
    common_names = [str(item.get("name")) for item in common_data.values() if item]
    check.require(len(common_paths) == 13, f"common agent set must contain exactly 13 TOMLs, found {len(common_paths)}")
    check.require(len(common_names) == len(set(common_names)), f"common agent names must be unique: {sorted(common_names)}")
    check.require(set(common_names) == EXPECTED_COMMON, f"common agent names mismatch: {sorted(common_names)}")
    pins = {
        "docs_researcher_luna.toml": ("docs_researcher_luna", "gpt-5.6-luna", "max"),
        "docs_researcher_terra.toml": ("docs_researcher_terra", "gpt-5.6-terra", "high"),
    }
    for filename, (name, model, effort) in pins.items():
        data = common_data.get(filename, {})
        check.require(data.get("name") == name, f"{filename} must provide {name}")
        check.require(data.get("model") == model, f"{filename} must pin {model}")
        check.require(data.get("model_reasoning_effort") == effort, f"{filename} must use {effort} effort")
        check.require(data.get("sandbox_mode") == "read-only", f"{filename} must use read-only sandbox")


def _compile_required(root: Path, check: Validation, helper: str, focused_test: str, label: str) -> None:
    helper_path, test_path = root / helper, root / focused_test
    check.require(helper_path.is_file(), f"missing {label} helper: {helper_path}")
    check.require(test_path.is_file(), f"missing {label} test: {test_path}")
    for path in (helper_path, test_path):
        if path.is_file():
            try:
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
            except (OSError, SyntaxError) as exc:
                check.errors.append(f"invalid Python {label} file {path}: {exc}")


def validate_runtime_records(root: Path, check: Validation) -> None:
    _compile_required(root, check, "payload/skills/versatile-dev/scripts/runtime_records.py", "tests/test_runtime_records.py", "runtime-record")
    fixture_dir = root / "tests/fixtures/runtime"
    actual = {path.name for path in fixture_dir.iterdir()} if fixture_dir.is_dir() else set()
    check.require(actual == RUNTIME_RECORD_FIXTURES, f"runtime fixture set mismatch: {sorted(actual)}")


def validate_route_research(root: Path, check: Validation) -> None:
    _compile_required(root, check, "payload/skills/versatile-dev/scripts/route_research.py", "tests/test_routing_state.py", "route-research")
    fixture_dir = root / "tests/fixtures/routing"
    actual = {path.name for path in fixture_dir.iterdir()} if fixture_dir.is_dir() else set()
    check.require(actual == ROUTING_FIXTURES, f"routing fixture set mismatch: {sorted(actual)}")


def validate_runtime_audit(root: Path, check: Validation) -> None:
    _compile_required(root, check, "payload/skills/versatile-dev/scripts/runtime_audit.py", "tests/test_manifest_audit.py", "runtime-audit")


def validate_root(root: Path, check: Validation) -> None:
    required = (
        "VERSION",
        "README.md",
        "DEVELOPMENT_PLAN.md",
        "install.sh",
        "validate.sh",
        "package.sh",
        "scripts/merge_config.py",
        "scripts/ensure_snippet.py",
        "scripts/write_manifest.py",
        "payload/config/agents.toml.snippet",
        "payload/AGENTS.md.snippet",
    )
    for relative in required:
        check.require((root / relative).is_file(), f"missing required file: {relative}")
    snippet_path = root / "payload/config/agents.toml.snippet"
    if snippet_path.is_file():
        try:
            snippet = tomllib.loads(snippet_path.read_text(encoding="utf-8"))["agents"]
        except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
            check.errors.append(f"invalid agents config snippet: {exc}")
        else:
            expected = {
                "enabled": True,
                "max_concurrent_threads_per_session": 6,
                "default_subagent_model": "gpt-5.6-terra",
                "default_subagent_reasoning_effort": "medium",
                "interrupt_message": True,
            }
            check.require(snippet == expected, f"agents config snippet drifted: {snippet}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=Path.cwd(), type=Path)
    root = parser.parse_args().root.resolve()
    check = Validation()
    validate_root(root, check)
    validate_skill(root, check)
    validate_agents(root, check)
    validate_runtime_records(root, check)
    validate_route_research(root, check)
    validate_runtime_audit(root, check)
    if check.errors:
        for error in check.errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Bundle validation failed with {len(check.errors)} error(s).", file=sys.stderr)
        return 1
    print("Bundle validation passed: skill + 13-agent dual-researcher bundle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
