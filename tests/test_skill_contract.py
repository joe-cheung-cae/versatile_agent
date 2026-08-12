#!/usr/bin/env python3
"""Offline semantic contract checks for the versatile-dev Skill."""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "payload/skills/versatile-dev/SKILL.md"
UI_PATH = ROOT / "payload/skills/versatile-dev/agents/openai.yaml"
REFERENCE_DIR = ROOT / "payload/skills/versatile-dev/references"
VALIDATOR_PATH = ROOT / "scripts/validate_bundle.py"
VALIDATOR_SPEC = importlib.util.spec_from_file_location("validate_bundle_for_skill_contract", VALIDATOR_PATH)
if VALIDATOR_SPEC is None or VALIDATOR_SPEC.loader is None:
    raise RuntimeError(f"unable to load validator: {VALIDATOR_PATH}")
VALIDATOR = importlib.util.module_from_spec(VALIDATOR_SPEC)
sys.modules[VALIDATOR_SPEC.name] = VALIDATOR
VALIDATOR_SPEC.loader.exec_module(VALIDATOR)
REQUIRED_REFERENCES = {
    "cuda-cae-review-policy.md",
    "model-routing.md",
    "review-policy.md",
    "task-contract.md",
    "workflow.md",
}
STALE_CLAIMS = (
    "current implementation boundary",
    "installed bundle provides exactly one",
    "legacy single configured",
    "dual-agent installer",
    "future work",
    "live conformance",
    "automatic model fallback",
    "cli automatic model fallback",
    "probe proves effective route",
)
APP_LANE_FRAGMENTS = [
    "App user-visible task lane",
    "explicit authorization in the current user request",
    "separate from native",
    "cannot establish native effective model or effort",
    "cannot authorize native Terra fallback",
]


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


def require_fragments(text: str, fragments: list[str]) -> None:
    lowered = text.casefold()
    missing = [fragment for fragment in fragments if fragment.casefold() not in lowered]
    if missing:
        raise AssertionError(f"missing contract fragments: {missing}")


def require_app_lane_contract(text: str) -> None:
    require_fragments(text, APP_LANE_FRAGMENTS)


def require_no_stale_claims(text: str) -> None:
    lowered = text.casefold()
    found = [claim for claim in STALE_CLAIMS if claim.casefold() in lowered]
    if found:
        raise AssertionError(f"stale Skill claims found: {found}")


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
        self.assertEqual(
            VALIDATOR.task_contract_violations(self.references["task-contract.md"]),
            [],
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
        require_app_lane_contract(self.routing)
        require_fragments(
            self.routing,
            [
                "installation manifest",
                "installed/configured facts",
                "observed native effective facts",
                "same-attempt native runtime details",
                "parent model",
                "bypasses permissions",
                "guarantees a model",
                "automatic CLI routing",
                "automatic CLI fallback",
            ],
        )
        self.assertEqual(
            VALIDATOR.semantic_contract_violations(self.skill, self.references, self.ui),
            [],
        )

    def test_reference_topology_is_exact_and_first_level(self) -> None:
        self.assertEqual(
            VALIDATOR.reference_topology_violations(self.skill, self.references, SKILL_PATH),
            [],
        )

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
        require_no_stale_claims(corpus)
        self.assertEqual(
            VALIDATOR.semantic_contract_violations(self.skill, self.references, self.ui),
            [],
        )

    def test_validator_ignores_legitimate_negated_contract_prose(self) -> None:
        negated = self.skill + "\n".join(
            (
                "",
                "Content failures never authorize Terra.",
                "The Skill does not change the parent model or permissions.",
                "A probe cannot establish the native effective route.",
                "Do not spawn all specialists by default.",
                "The App task cannot be created without explicit authorization.",
                "Content failures never authorize Terra fallback.",
                "Content failures authorize no Terra fallback.",
                "Terra fallback is not authorized by content failures.",
                "The manifest does not prove the effective route.",
                "The effective route is not proven by the manifest.",
                "This Skill does not switch the parent model.",
                "The parent model is not switched by this Skill.",
            )
        )
        self.assertEqual(
            VALIDATOR.semantic_contract_violations(negated, self.references, self.ui),
            [],
        )

    def test_validator_polarity_matrix(self) -> None:
        rejected = (
            "Content failures authorize Terra fallback.",
            "Terra fallback is authorized by content failures.",
            "The installation manifest proves the effective native route.",
            "The effective native route is proven by the installation manifest.",
            "This Skill switches the parent model.",
            "The parent model is switched by this Skill.",
            "The App task cannot be created without explicit authorization, but content failures authorize Terra fallback.",
        )
        for addition in rejected:
            with self.subTest(sentence=addition):
                self.assertTrue(
                    VALIDATOR.semantic_contract_violations(
                        self.skill + "\n" + addition,
                        self.references,
                        self.ui,
                    ),
                    addition,
                )

        accepted = (
            "Content failures never authorize Terra fallback.",
            "Content failures authorize no Terra fallback.",
            "Terra fallback is not authorized by content failures.",
            "The manifest does not prove the effective route.",
            "The effective route is not proven by the manifest.",
            "This Skill does not switch the parent model.",
            "The parent model is not switched by this Skill.",
        )
        for addition in accepted:
            with self.subTest(sentence=addition):
                self.assertEqual(
                    VALIDATOR.semantic_contract_violations(
                        self.skill + "\n" + addition,
                        self.references,
                        self.ui,
                    ),
                    [],
                )

    def test_app_authorization_exception_matrix(self) -> None:
        rejected = (
            "Authorization from an earlier request is also acceptable.",
            "Prior request authorization is sufficient for App tasks.",
            "App tasks accept previous request authorization.",
            "Unless previously authorized, create an App task.",
            "Implied consent is sufficient for App tasks.",
            "App task creation accepts implied consent.",
            "Current-request authorization is optional.",
            "Current-request authorization may be omitted.",
            "App task may be created without explicit authorization.",
        )
        for addition in rejected:
            with self.subTest(sentence=addition):
                self.assertTrue(
                    VALIDATOR.semantic_contract_violations(
                        self.skill + "\n" + addition,
                        self.references,
                        self.ui,
                    ),
                    addition,
                )

        accepted = (
            "Earlier authorization is not sufficient.",
            "Implied consent is not accepted.",
            "Current-request authorization is not optional.",
            "The App task cannot be created without explicit authorization.",
        )
        for addition in accepted:
            with self.subTest(sentence=addition):
                self.assertEqual(
                    VALIDATOR.semantic_contract_violations(
                        self.skill + "\n" + addition,
                        self.references,
                        self.ui,
                    ),
                    [],
                )

    def test_mutated_in_memory_contracts_fail(self) -> None:
        missing_packet_link = self.skill.replace(
            "references/task-contract.md",
            "references/removed-task-contract.md",
        )
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(missing_packet_link, self.references, SKILL_PATH),
                [],
            )

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

        weakened_app_lane = self.routing.replace(
            "explicit authorization in the current user request",
            "an authorization signal",
        )
        with self.assertRaises(AssertionError):
            require_app_lane_contract(weakened_app_lane)

        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.semantic_contract_violations(weakened_app_lane, self.references, self.ui),
                [],
            )

        stale_claim = self.skill + "\nThe dual-agent installer is pending and not implemented.\n"
        with self.assertRaises(AssertionError):
            require_no_stale_claims(stale_claim)
        stale_skill = self.skill + "\nThe dual-agent installer is pending and not implemented.\n"
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.semantic_contract_violations(stale_skill, self.references, self.ui),
                [],
            )

        contradictory_additions = (
            "App tasks may be created by default.",
            "App tasks require no explicit authorization.",
            "No authorization is required for App tasks.",
            "Prior authorization is enough for App tasks.",
            "Implicit authorization is allowed for creating App tasks.",
            "App tasks may be created without explicit authorization.",
            "Content failures may trigger Terra fallback.",
            "The dual researchers are pending and not installed.",
            "The route helper is future work.",
            "Spawn all specialists by default.",
            "Delegate every reviewer automatically.",
            "Use a fixed specialist pipeline.",
            "Automatic CLI model switching is enabled.",
            "The CLI automatically switches models.",
            "Automatic model fallback is enabled.",
            "A probe proves the effective native route.",
            "The Skill changes the parent model and permissions.",
            "The Skill guarantees model availability.",
            "The installed bundle provides exactly one legacy docs_researcher.",
            "The current implementation boundary is future work.",
            "Live conformance is future work.",
        )
        for addition in contradictory_additions:
            with self.subTest(addition=addition), self.assertRaises(AssertionError):
                self.assertEqual(
                    VALIDATOR.semantic_contract_violations(
                        self.skill + "\n" + addition,
                        self.references,
                        self.ui,
                    ),
                    [],
                )

        nested_reference_map = dict(self.references)
        nested_reference_map["workflow.md"] += "\n[Routing](./model-routing.md?x=1#y)\n"
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(self.skill, nested_reference_map, SKILL_PATH),
                [],
            )

        reference_style_map = dict(self.references)
        reference_style_map["workflow.md"] += "\n[route]: ./model-routing.md?x=1#y\n[Routing][route]\n"
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(self.skill, reference_style_map, SKILL_PATH),
                [],
            )

        external_reference_map = dict(self.references)
        external_reference_map["workflow.md"] += "\n[Docs](https://example.com/model-routing.md?x=1#y)\n[Mail](mailto:docs@example.com)\n"
        self.assertEqual(
            VALIDATOR.reference_topology_violations(self.skill, external_reference_map, SKILL_PATH),
            [],
        )

        packet = self.references["task-contract.md"]
        packet_mutations = (
            packet + "\n## Extra\n",
            packet + "\n### 6 Extra\n",
            packet + "\nSetext heading\n---\n",
            packet.replace("## 2. Ownership", "## 1. Duplicate\n\n## 2. Ownership"),
            packet.replace("## 3. Inputs/evidence", "## 4. Constraints/requirements\n\n## 3. Inputs/evidence"),
        )
        for mutation in packet_mutations:
            with self.subTest(packet=mutation), self.assertRaises(AssertionError):
                self.assertEqual(VALIDATOR.task_contract_violations(mutation), [])
        self.assertEqual(
            VALIDATOR.task_contract_violations(packet + "\n- ordinary packet detail\n"),
            [],
        )


if __name__ == "__main__":
    unittest.main()
