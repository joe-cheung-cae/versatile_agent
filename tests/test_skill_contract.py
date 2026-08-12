#!/usr/bin/env python3
"""Offline semantic contract checks for the versatile-dev Skill."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "payload/skills/versatile-dev/SKILL.md"
UI_PATH = ROOT / "payload/skills/versatile-dev/agents/openai.yaml"
REFERENCE_DIR = ROOT / "payload/skills/versatile-dev/references"
REQUIRED_REFERENCES = {
    "cuda-cae-review-policy.md",
    "model-routing.md",
    "review-policy.md",
    "task-contract.md",
    "workflow.md",
}


def frontmatter(text: str) -> tuple[list[str], str]:
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    if match is None:
        raise AssertionError("SKILL.md is missing YAML frontmatter")
    block = match.group(1)
    keys = [line.split(":", 1)[0].strip() for line in block.splitlines() if ":" in line]
    description_match = re.search(r"^description:\s*(.*)$", block, re.MULTILINE)
    if description_match is None:
        raise AssertionError("frontmatter is missing description")
    return keys, description_match.group(1)


def local_markdown_targets(text: str) -> list[str]:
    targets: list[str] = []
    for raw_target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
        target = raw_target.strip().split("#", 1)[0]
        if not target or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
            continue
        targets.append(target)
    return targets


def require_fragments(text: str, fragments: list[str]) -> None:
    lowered = text.casefold()
    missing = [fragment for fragment in fragments if fragment.casefold() not in lowered]
    if missing:
        raise AssertionError(f"missing contract fragments: {missing}")


def require_skill_topology(skill_text: str, skill_path: Path) -> None:
    targets = set(local_markdown_targets(skill_text))
    expected = {f"references/{name}" for name in REQUIRED_REFERENCES}
    if targets != expected:
        raise AssertionError(f"main Skill links drifted: {sorted(targets)}")
    for target in targets:
        resolved = (skill_path.parent / target).resolve()
        if not resolved.is_file():
            raise AssertionError(f"unresolved Skill reference: {target}")


class SkillContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill = SKILL_PATH.read_text(encoding="utf-8")
        cls.ui = UI_PATH.read_text(encoding="utf-8")
        cls.references = {
            path.name: path.read_text(encoding="utf-8")
            for path in REFERENCE_DIR.glob("*.md")
        }
        cls.routing = cls.skill + "\n" + cls.references["model-routing.md"]

    def test_frontmatter_triggers_and_ui_prompt(self) -> None:
        keys, description = frontmatter(self.skill)
        self.assertEqual(keys, ["name", "description"])
        self.assertIn("name: versatile-dev", self.skill.split("---", 2)[1])

        prefix = description[:420].casefold()
        self.assertIn("non-trivial repository engineering", prefix)
        self.assertIn("mapping", prefix)
        self.assertIn("planning", prefix)
        self.assertIn("independent review", prefix)
        self.assertIn("do not use for simple q&a or status-only work", prefix)
        self.assertIn("parent model", prefix)
        self.assertIn("probes", prefix)
        self.assertRegex(self.ui, r"(?m)^\s*default_prompt:\s*.*\$versatile-dev")

    def test_lead_packet_direct_path_review_and_acceptance_contract(self) -> None:
        require_fragments(
            self.skill,
            [
                "lead engineer",
                "user's intent",
                "architecture",
                "task state",
                "integration",
                "diff",
                "tests",
                "acceptance",
                "references/task-contract.md",
                "Objective",
                "Ownership",
                "Inputs/evidence",
                "Constraints/requirements",
                "Verification/handoff",
                "simple obvious changes",
                "One writer owns overlapping",
                "agent that did not author",
                "correction invalidates",
                "Only the lead accepts completion",
            ],
        )
        require_fragments(
            self.references["task-contract.md"],
            [
                "## 1. Objective",
                "## 2. Ownership",
                "## 3. Inputs/evidence",
                "## 4. Constraints/requirements",
                "## 5. Verification/handoff",
            ],
        )

    def test_current_dual_route_and_fail_closed_semantics(self) -> None:
        require_fragments(
            self.routing,
            [
                "docs_researcher_luna",
                "gpt-5.6-luna",
                "max",
                "docs_researcher_terra",
                "gpt-5.6-terra",
                "route_research.py",
                "runtime_audit.py",
                "same-interface",
                "PRECHECK",
                "STOP_UNVERIFIED",
                "FALLBACK_PENDING",
                "at most one",
                "same canonical `task_packet_hash`",
                "Content, tool,\ntask, timeout, and unknown-exception outcomes never authorize Terra",
            ],
        )
        self.assertRegex(
            self.routing,
            r"(?is)missing.{0,90}conflicting.{0,90}unobservable.{0,100}STOP_UNVERIFIED",
        )
        self.assertRegex(self.routing, r"(?is)native\s+routing\s+rejection")
        self.assertIn("complete same-attempt native route mismatch", self.routing.casefold())

    def test_evidence_layers_and_app_lane_are_separate(self) -> None:
        require_fragments(
            self.routing,
            [
                "installation manifest",
                "installed/configured facts",
                "observed native effective facts",
                "same-attempt native runtime details",
                "App user-visible task lane",
                "explicit authorization in the current user request",
                "separate from native",
                "cannot establish native effective model or effort",
                "cannot authorize native Terra fallback",
                "parent model",
                "bypasses permissions",
                "guarantees a model",
                "automatic CLI routing",
                "automatic CLI fallback",
            ],
        )

    def test_reference_topology_is_exact_and_first_level(self) -> None:
        self.assertEqual(set(self.references), REQUIRED_REFERENCES)
        require_skill_topology(self.skill, SKILL_PATH)
        for name, text in self.references.items():
            nested = [target for target in local_markdown_targets(text) if target.endswith(".md")]
            self.assertEqual(nested, [], f"{name} links to another local reference: {nested}")

    def test_selective_specialist_boundaries(self) -> None:
        require_fragments(
            self.skill + "\n" + self.references["cuda-cae-review-policy.md"],
            [
                "gpu_reviewer",
                "numerics_reviewer",
                "parallelism_reviewer",
                "performance_profiler",
                "security_reviewer",
                "test_validator",
                "reviewer",
                "only the specialists whose boundaries are touched",
                "Never spawn all specialists by default",
                "Do not start every specialist",
            ],
        )

    def test_stale_claims_are_absent(self) -> None:
        corpus = "\n".join([self.skill, *self.references.values(), self.ui]).casefold()
        for stale in (
            "current implementation boundary",
            "installed bundle provides exactly one",
            "legacy single configured",
            "dual-agent installer",
            "future work",
            "live conformance",
            "automatic model fallback",
            "cli automatic model fallback",
            "probe proves effective route",
        ):
            self.assertNotIn(stale, corpus)

    def test_mutated_in_memory_contracts_fail(self) -> None:
        missing_packet_link = self.skill.replace(
            "references/task-contract.md",
            "references/removed-task-contract.md",
        )
        with self.assertRaises(AssertionError):
            require_skill_topology(missing_packet_link, SKILL_PATH)

        missing_lead_responsibility = self.skill.replace("Own the user's intent", "Ignore the user's intent")
        with self.assertRaises(AssertionError):
            require_fragments(missing_lead_responsibility, ["Own the user's intent"])

        missing_fallback_guard = self.routing.replace(
            "never authorize Terra",
            "may authorize Terra",
        )
        with self.assertRaises(AssertionError):
            require_fragments(
                missing_fallback_guard,
                ["Content, tool,\ntask, timeout, and unknown-exception outcomes never authorize Terra"],
            )


if __name__ == "__main__":
    unittest.main()
