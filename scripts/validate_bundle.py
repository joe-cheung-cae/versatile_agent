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
    common_dir = root / "payload/agents/common"
    common_data = [parse_agent(path, check) for path in sorted(common_dir.glob("*.toml"))]
    common_names = {str(item.get("name")) for item in common_data if item}
    check.require(common_names == EXPECTED_COMMON, f"common agent set mismatch: {sorted(common_names)}")

    luna_path = root / "payload/agents/profiles/luna-v1/docs_researcher.toml"
    terra_path = root / "payload/agents/profiles/terra-fallback/docs_researcher.toml"
    luna = parse_agent(luna_path, check)
    terra = parse_agent(terra_path, check)
    check.require(luna.get("name") == "docs_researcher", "Luna profile must provide docs_researcher")
    check.require(luna.get("model") == "gpt-5.6-luna", "Luna profile must pin gpt-5.6-luna")
    check.require(luna.get("model_reasoning_effort") == "max", "Luna profile must use max effort")
    check.require(terra.get("name") == "docs_researcher", "Terra fallback must provide docs_researcher")
    check.require(terra.get("model") == "gpt-5.6-terra", "Fallback profile must pin gpt-5.6-terra")
    check.require(terra.get("model_reasoning_effort") == "high", "Fallback profile must use high effort")

    for profile_name, profile_data in (("luna-v1", luna), ("terra-fallback", terra)):
        names = common_names | ({str(profile_data.get("name"))} if profile_data else set())
        check.require(len(names) == 12, f"{profile_name} must resolve to exactly 12 unique agents, found {len(names)}")


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

    if check.errors:
        for error in check.errors:
            print(f"ERROR: {error}", file=sys.stderr)
        print(f"Bundle validation failed with {len(check.errors)} error(s).", file=sys.stderr)
        return 1
    print("Bundle validation passed: skill + 12-agent Luna/Terra profile matrix.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
