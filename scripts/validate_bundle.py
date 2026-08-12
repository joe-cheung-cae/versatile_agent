#!/usr/bin/env python3
"""Structural and semantic validation for the distributable bundle."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path


REQUIRED_AGENT_KEYS = {"name", "description", "developer_instructions", "model", "model_reasoning_effort", "sandbox_mode"}
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
    "cuda-cae-review-policy.md",
    "model-routing.md",
    "review-policy.md",
    "task-contract.md",
    "workflow.md",
}
TASK_CONTRACT_HEADINGS = (
    "## 1. Objective",
    "## 2. Ownership",
    "## 3. Inputs/evidence",
    "## 4. Constraints/requirements",
    "## 5. Verification/handoff",
)
INLINE_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(\s*(?:<([^>]+)>|([^\s)]+))")
REFERENCE_DEFINITION_RE = re.compile(r"(?m)^[ \t]{0,3}\[[^\]]+\]:[ \t]*(?:<([^>\n]+)>|(\S+))")
NUMBERED_HEADING_RE = re.compile(r"(?m)^#{1,6}[ \t]+\d+\.[ \t]+.+?[ \t]*$")
CONTRACT_NEGATION_RE = re.compile(
    r"\b(?:not|never|no|cannot|can't|doesn't|does not|do not|don't|without|must not|should not)\b"
)


def _normalize_contract_text(text: str) -> str:
    """Normalize prose enough for small, deterministic semantic checks."""

    normalized = text.casefold().replace("’", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", normalized).strip()


def _positive_contract_match(text: str, pattern: re.Pattern[str]) -> re.Match[str] | None:
    """Find a positive contradiction while ignoring nearby explicit negation."""

    for match in pattern.finditer(text):
        context_start = max(0, match.start() - 140)
        context = text[context_start : match.start()]
        context = re.split(r"[.!?;]", context)[-1]
        action_prefix = match.group(0)
        action_match = re.search(
            r"\b(?:authorize|authorizes|trigger|triggers|permit|permits|allow|allows|allowed|enable|enables|change|changes|switch|switches|control|controls|override|overrides|prove|proves|establish|establishes|demonstrate|demonstrates|confirm|confirms|guarantee|guarantees|ensure|ensures|provide|provides|create|creates|created|creating)\b",
            action_prefix,
        )
        if action_match:
            action_prefix = action_prefix[: action_match.start()]
            negated = CONTRACT_NEGATION_RE.search(context) or CONTRACT_NEGATION_RE.search(action_prefix)
        else:
            negated = CONTRACT_NEGATION_RE.search(context)
        if negated:
            continue
        return match
    return None


CONTRACT_CONTRADICTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "App task may bypass current-request authorization",
        re.compile(
            r"(?:\bapp(?:\s+user-visible)?\s+tasks?\b.{0,100}\b(?:requires?|needs?|need)\s+no\s+(?:explicit\s+)?authori[sz]ation\b|\bno\s+(?:explicit\s+)?authori[sz]ation\s+(?:is\s+)?required\b.{0,100}\bapp(?:\s+user-visible)?\s+tasks?\b)"
        ),
    ),
    (
        "App task accepts prior or implicit authorization",
        re.compile(
            r"(?:\b(?:prior|previous|earlier|past)\s+authori[sz]ation\b.{0,100}\b(?:is\s+enough|is\s+sufficient|suffices|is\s+accepted)\b.{0,80}\b(?:app(?:\s+user-visible)?\s+tasks?|create|creating)\b|\b(?:prior|previous|earlier|past)\s+authori[sz]ation\b.{0,80}\b(?:app(?:\s+user-visible)?\s+tasks?|create|creating)\b.{0,100}\b(?:is\s+enough|is\s+sufficient|suffices|is\s+accepted)\b)"
        ),
    ),
    (
        "App task accepts implicit authorization",
        re.compile(
            r"\b(?:implicit|implied)\s+authori[sz]ation\b.{0,100}\b(?:app(?:\s+user-visible)?\s+tasks?|create|creating)\b"
        ),
    ),
    (
        "App task may omit authorization",
        re.compile(
            r"(?:\bapp(?:\s+user-visible)?\s+tasks?\b.{0,100}\b(?:without|with\s+no)\s+(?:an?\s+)?(?:explicit\s+)?authori[sz]ation\b|\b(?:without|with\s+no)\s+(?:an?\s+)?(?:explicit\s+)?authori[sz]ation\b.{0,100}\bapp(?:\s+user-visible)?\s+tasks?\b)"
        ),
    ),
    (
        "App task may be created by default",
        re.compile(
            r"\bapp(?:\s+user-visible)?\s+tasks?\b.{0,100}\b(?:may|can|will)\s+(?:be\s+)?creat(?:e|ed|ing)\b.{0,40}\bby default\b"
        ),
    ),
    (
        "Non-routing failures may authorize Terra or fallback",
        re.compile(
            r"\b(?:content|tool|task|timeout|unknown(?:[-\s]+exception)?)(?:\s*(?:[/,&]|\band\b)\s*(?:content|tool|task|timeout|unknown(?:[-\s]+exception)?))*\s+(?:failure|failures|error|errors|outcome|outcomes|exception|exceptions)?\s*.{0,90}\b(?:authorize|authorizes|trigger|triggers|permit|permits|allow|allows|enable|enables)\b.{0,40}\b(?:terra|fallback)\b"
        ),
    ),
    (
        "Dual researchers or routing helper described as incomplete",
        re.compile(
            r"\b(?:dual[-\s]?(?:researcher|agent)s?|dual[-\s]?agent installer|docs_researcher_luna\s*(?:and|/)\s*docs_researcher_terra|(?:two|both)\s+(?:named\s+)?researchers?|route_research\.py|(?:route|routing)(?:[-\s]+research)?[-\s]+helper)\b.{0,120}\b(?:future|pending|not installed|not implemented|unimplemented|planned|later)\b"
        ),
    ),
    (
        "Legacy single-only researcher route described as current",
        re.compile(r"(?:\blegacy\s+single(?:[-\s]+only)?\b|\binstalled\s+bundle\s+provides\s+exactly\s+one\b.{0,60}\b(?:legacy\s+)?docs_researcher\b|\blegacy\s+single\s+configured\b)"),
    ),
    (
        "All or every specialist is selected by default",
        re.compile(
            r"\b(?:spawn|run|start|delegate|launch|schedule|use)\b.{0,60}\b(?:all|every)\s+(?:the\s+)?(?:specialists?|reviewers?|agents?)\b.{0,40}\b(?:by default|as default|automatically)\b"
        ),
    ),
    (
        "Fixed specialist pipeline is required",
        re.compile(r"\b(?:fixed|predefined|rigid)\s+(?:agent|specialist)\s+(?:pipeline|sequence|roster)\b"),
    ),
    (
        "CLI automatic fallback or model switching is enabled",
        re.compile(
            r"(?:\bautomatic\s+cli\s+(?:fallback|model\s+switch(?:ing)?)\b|\bautomatic\s+model\s+fallback\b|\bcli\b.{0,40}\bautomatically\s+(?:switch(?:es|ing)?\s+models?|fallback)\b)"
        ),
    ),
    (
        "Stale implementation or live-conformance claim",
        re.compile(
            r"(?:\bcurrent\s+implementation\s+boundary\b|\blive\s+conformance\b.{0,80}\b(?:future|pending|not implemented|planned)\b)"
        ),
    ),
    (
        "Probe, manifest, or App task proves effective route",
        re.compile(
            r"\b(?:probe|install(?:ation)?\s+manifest|app(?:\s+user-visible)?\s+task(?:\s+result)?s?)\b.{0,90}\b(?:proves?|establishes?|demonstrates?|confirms?)\b.{0,70}\b(?:effective|native)\b"
        ),
    ),
    (
        "Skill changes parent model or permissions",
        re.compile(
            r"\bskill\b.{0,90}\b(?:changes?|switches?|controls?|overrides?)\b.{0,60}\b(?:parent\s+model|permissions?)\b"
        ),
    ),
    (
        "Skill guarantees model availability",
        re.compile(r"\b(?:guarantees?|ensures?)\b.{0,50}\b(?:model\s+)?availability\b"),
    ),
)
REQUIRED_CONTRACT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "App task must require explicit current-request authorization",
        re.compile(
            r"\bcreate\s+an?\s+app(?:\s+user-visible)?\s+task\b.{0,80}\bonly\s+after\s+explicit\s+authori[sz]ation\s+in\s+the\s+current\s+user\s+request\b"
        ),
    ),
)


def _normalize_markdown_target(raw_target: str) -> str | None:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if not target or target.startswith("//") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
        return None
    target = re.split(r"[?#]", target, maxsplit=1)[0]
    while target.startswith("./"):
        target = target[2:]
    return target or None


def extract_local_markdown_targets(text: str) -> list[str]:
    """Extract normalized local targets from inline and reference-style links."""

    raw_targets: list[str] = []
    for match in INLINE_MARKDOWN_LINK_RE.finditer(text):
        raw_targets.append(match.group(1) or match.group(2))
    for match in REFERENCE_DEFINITION_RE.finditer(text):
        raw_targets.append(match.group(1) or match.group(2))
    targets: list[str] = []
    for raw_target in raw_targets:
        target = _normalize_markdown_target(raw_target)
        if target is not None:
            targets.append(target)
    return targets


def semantic_contract_violations(
    skill_text: str,
    reference_map: Mapping[str, str],
    ui_text: str = "",
) -> list[str]:
    """Return explicit contradiction labels for the frozen Skill contract."""

    reference_text = (reference_map[name] for name in sorted(reference_map))
    corpus = _normalize_contract_text("\n".join((skill_text, *reference_text, ui_text)))
    violations: list[str] = []
    for label, pattern in CONTRACT_CONTRADICTION_PATTERNS:
        if _positive_contract_match(corpus, pattern) is not None:
            violations.append(label)
    skill_corpus = _normalize_contract_text(skill_text)
    for label, pattern in REQUIRED_CONTRACT_PATTERNS:
        if pattern.search(skill_corpus) is None:
            violations.append(label)
    return violations


def task_contract_violations(text: str) -> list[str]:
    """Require exactly the five numbered task-packet headings in order."""

    headings = [match.group(0).strip() for match in NUMBERED_HEADING_RE.finditer(text)]
    if headings != list(TASK_CONTRACT_HEADINGS):
        return [f"task-contract numbered headings must be exactly {list(TASK_CONTRACT_HEADINGS)}: {headings}"]
    return []


def reference_topology_violations(
    skill_text: str,
    reference_map: Mapping[str, str],
    skill_path: Path | None = None,
) -> list[str]:
    """Validate direct Skill links and reject reference-to-reference links."""

    violations: list[str] = []
    actual_references = set(reference_map)
    if actual_references != SKILL_REFERENCE_FILES:
        violations.append(
            f"skill references must be exactly {sorted(SKILL_REFERENCE_FILES)}: {sorted(actual_references)}"
        )

    expected_links = {f"references/{name}" for name in SKILL_REFERENCE_FILES}
    local_links = set(extract_local_markdown_targets(skill_text))
    if local_links != expected_links:
        violations.append(f"SKILL.md links must resolve to direct references only: {sorted(local_links)}")

    if skill_path is not None:
        for target in local_links:
            if not (skill_path.parent / target).is_file():
                violations.append(f"SKILL.md has an unresolved local link: {target}")

    for name, text in reference_map.items():
        nested_links = [target for target in extract_local_markdown_targets(text) if target.casefold().endswith(".md")]
        if nested_links:
            violations.append(f"skill reference must not link to another local reference: {name}: {nested_links}")
    return violations


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


def validate_skill(root: Path, check: Validation) -> None:
    skill = root / "payload/skills/versatile-dev/SKILL.md"
    check.require(skill.is_file(), f"missing {skill}")
    if not skill.is_file():
        return
    text = skill.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    check.require(match is not None, "SKILL.md must begin with YAML frontmatter")
    if match:
        frontmatter = match.group(1)
        keys = [line.split(":", 1)[0].strip() for line in frontmatter.splitlines() if ":" in line]
        check.require(keys == ["name", "description"], f"SKILL.md frontmatter keys must be name and description only: {keys}")
        check.require("name: versatile-dev" in frontmatter, "SKILL.md name must be versatile-dev")
        check.require("TODO" not in text, "SKILL.md still contains TODO text")

    ui = root / "payload/skills/versatile-dev/agents/openai.yaml"
    ui_text = ""
    check.require(ui.is_file(), "missing agents/openai.yaml")
    if ui.is_file():
        ui_text = ui.read_text(encoding="utf-8")
        check.require("$versatile-dev" in ui_text, "openai.yaml default_prompt must mention $versatile-dev")

    reference_dir = root / "payload/skills/versatile-dev/references"
    actual_references = {item.name for item in reference_dir.glob("*.md")}
    check.require(
        actual_references == SKILL_REFERENCE_FILES,
        f"skill references must be exactly {sorted(SKILL_REFERENCE_FILES)}: {sorted(actual_references)}",
    )
    reference_map = {
        path.name: path.read_text(encoding="utf-8")
        for path in reference_dir.glob("*.md")
    }
    for violation in semantic_contract_violations(text, reference_map, ui_text):
        check.errors.append(f"Skill semantic contradiction: {violation}")
    for violation in task_contract_violations(reference_map.get("task-contract.md", "")):
        check.errors.append(violation)
    for violation in reference_topology_violations(text, reference_map, skill):
        check.errors.append(violation)


def validate_agents(root: Path, check: Validation) -> None:
    for obsolete in (
        root / "payload/agents/profiles/luna-v1/docs_researcher.toml",
        root / "payload/agents/profiles/terra-fallback/docs_researcher.toml",
    ):
        check.require(not obsolete.exists() and not obsolete.is_symlink(), f"obsolete profile payload must be absent: {obsolete}")

    common_dir = root / "payload/agents/common"
    common_paths = sorted(common_dir.glob("*.toml"))
    common_data = {path.name: parse_agent(path, check) for path in common_paths}
    common_files = set(common_data)
    check.require(
        common_files == EXPECTED_COMMON_FILES,
        f"common agent files mismatch: {sorted(common_files)}",
    )

    common_names = [str(item.get("name")) for item in common_data.values() if item]
    check.require(len(common_paths) == 13, f"common agent set must contain exactly 13 TOMLs, found {len(common_paths)}")
    check.require(
        len(common_names) == len(set(common_names)),
        f"common agent names must be unique: {sorted(common_names)}",
    )
    check.require(set(common_names) == EXPECTED_COMMON, f"common agent names mismatch: {sorted(common_names)}")

    researcher_pins = {
        "docs_researcher_luna.toml": ("docs_researcher_luna", "gpt-5.6-luna", "max"),
        "docs_researcher_terra.toml": ("docs_researcher_terra", "gpt-5.6-terra", "high"),
    }
    for filename, (name, model, effort) in researcher_pins.items():
        data = common_data.get(filename, {})
        check.require(data.get("name") == name, f"{filename} must provide {name}")
        check.require(data.get("model") == model, f"{filename} must pin {model}")
        check.require(data.get("model_reasoning_effort") == effort, f"{filename} must use {effort} effort")
        check.require(data.get("sandbox_mode") == "read-only", f"{filename} must use read-only sandbox")


def validate_runtime_records(root: Path, check: Validation) -> None:
    helper = root / "payload/skills/versatile-dev/scripts/runtime_records.py"
    focused_test = root / "tests/test_runtime_records.py"
    check.require(helper.is_file(), f"missing runtime-record helper: {helper}")
    check.require(focused_test.is_file(), f"missing runtime-record test: {focused_test}")
    for path in (helper, focused_test):
        if path.is_file():
            try:
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
            except (OSError, SyntaxError) as exc:
                check.errors.append(f"invalid Python runtime-record file {path}: {exc}")

    fixture_dir = root / "tests/fixtures/runtime"
    actual_fixtures = {path.name for path in fixture_dir.iterdir()} if fixture_dir.is_dir() else set()
    check.require(
        actual_fixtures == RUNTIME_RECORD_FIXTURES,
        f"runtime fixture set mismatch: {sorted(actual_fixtures)}",
    )


def validate_route_research(root: Path, check: Validation) -> None:
    helper = root / "payload/skills/versatile-dev/scripts/route_research.py"
    focused_test = root / "tests/test_routing_state.py"
    check.require(helper.is_file(), f"missing route-research helper: {helper}")
    check.require(focused_test.is_file(), f"missing route-research test: {focused_test}")
    for path in (helper, focused_test):
        if path.is_file():
            try:
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
            except (OSError, SyntaxError) as exc:
                check.errors.append(f"invalid Python route-research file {path}: {exc}")

    fixture_dir = root / "tests/fixtures/routing"
    actual_fixtures = {path.name for path in fixture_dir.iterdir()} if fixture_dir.is_dir() else set()
    check.require(
        actual_fixtures == ROUTING_FIXTURES,
        f"routing fixture set mismatch: {sorted(actual_fixtures)}",
    )


def validate_runtime_audit(root: Path, check: Validation) -> None:
    helper = root / "payload/skills/versatile-dev/scripts/runtime_audit.py"
    focused_test = root / "tests/test_manifest_audit.py"
    check.require(helper.is_file(), f"missing runtime-audit helper: {helper}")
    check.require(focused_test.is_file(), f"missing manifest/audit test: {focused_test}")
    for path in (helper, focused_test):
        if path.is_file():
            try:
                compile(path.read_text(encoding="utf-8"), str(path), "exec")
            except (OSError, SyntaxError) as exc:
                check.errors.append(f"invalid Python manifest/audit file {path}: {exc}")


def validate_root(root: Path, check: Validation) -> None:
    for relative in (
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
    ):
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
    args = parser.parse_args()
    root = args.root.resolve()
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
