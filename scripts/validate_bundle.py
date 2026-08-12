#!/usr/bin/env python3
"""Structural and semantic validation for the distributable bundle."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
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
    check.require(ui.is_file(), "missing agents/openai.yaml")
    if ui.is_file():
        ui_text = ui.read_text(encoding="utf-8")
        check.require("$versatile-dev" in ui_text, "openai.yaml default_prompt must mention $versatile-dev")

    required_references = {
        "workflow.md",
        "task-contract.md",
        "review-policy.md",
        "cuda-cae-review-policy.md",
        "model-routing.md",
    }
    reference_dir = root / "payload/skills/versatile-dev/references"
    actual_references = {item.name for item in reference_dir.glob("*.md")}
    check.require(required_references <= actual_references, f"missing skill references: {sorted(required_references - actual_references)}")


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
