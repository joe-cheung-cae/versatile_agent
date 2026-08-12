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
                "Offline validation does not prove live runtime conformance.",
                "Live runtime conformance is not proven by offline validation.",
                "Do not create an App task without explicit authorization.",
                "Do not claim that content failures authorize Terra fallback.",
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
            "Content failures can authorize Terra fallback.",
            "Content failures could authorize Terra fallback.",
            "Content failures will authorize Terra fallback.",
            "Terra fallback can be authorized by content failures.",
            "Terra fallback could be authorized by content failures.",
            "If a task fails, use Terra.",
            "Content failures and native routing failures authorize Terra fallback.",
            "The installation manifest can prove the effective native route.",
            "The installation manifest could prove the effective native route.",
            "The effective native route can be proven by the installation manifest.",
            "The effective native route could be proven by the installation manifest.",
            "This Skill can switch the parent model.",
            "This Skill could switch the parent model.",
            "This Skill may change the parent model.",
            "The parent model can be switched by this Skill.",
            "The parent model could be switched by this Skill.",
            "Implicit consent suffices for App tasks.",
            "App tasks could be created without explicit authorization.",
            "The probe will confirm the effective native route.",
            "Offline validation will establish live runtime conformance.",
            "App tasks can rely on implied authorization.",
            "Create an App task unless the user opts out.",
            "Offline validation proves live runtime conformance.",
            "Live runtime conformance is proven by offline validation.",
            "The App task cannot be created without explicit authorization, but content failures authorize Terra fallback.",
            "Content failures never authorize Terra fallback, but Terra fallback can be authorized by content failures.",
            "Do not create an App task without explicit authorization, but App tasks could be created without explicit authorization.",
            "Do not claim that content failures authorize Terra fallback, but tool failures authorize Terra fallback.",
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
            "Content failures cannot authorize Terra fallback.",
            "Neither content failures nor tool failures authorize Terra fallback.",
            "Do not use Terra if a task fails.",
            "Terra fallback cannot be authorized by content failures.",
            "The installation manifest cannot prove the effective native route.",
            "The effective native route cannot be proven by the installation manifest.",
            "This Skill cannot switch the parent model.",
            "The parent model cannot be switched by this Skill.",
            "This Skill may not change the parent model.",
            "This Skill cannot perform automatic CLI fallback.",
            "The probe will not confirm the effective native route.",
            "Offline validation will not establish live runtime conformance.",
            "App tasks cannot rely on implied authorization.",
            "Do not create an App task unless explicitly authorized in the current user request.",
            "Implicit consent does not suffice for App tasks.",
            "Offline validation does not prove live runtime conformance.",
            "Live runtime conformance is not proven by offline validation.",
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

    def test_sensitive_contract_language_fails_closed(self) -> None:
        rejected = (
            "App tasks are opt-out rather than opt-in.",
            "App task creation may use authorization carried over from an earlier request.",
            "App tasks are not opt-out. They are authorized by previous requests.",
            "App tasks are not opt-out. Those tasks are created by default.",
            "Content failures do not authorize Terra fallback. They are sufficient reasons for Terra.",
            "App tasks are not opt-out while App tasks may rely on authorization carried over from an earlier request.",
            "When content fails, fall back to Terra.",
            "A timeout is sufficient reason to attempt Terra.",
            "Offline validation guarantees native runtime behavior.",
            "This Skill grants permissions.",
            "This Skill does not change the parent model while this Skill grants permissions.",
            "Content failures do not never authorize Terra fallback.",
            "App tasks may rely on authorization from a prior request.",
            "Content failures and native routing failures may authorize Terra fallback.",
        )
        for addition in rejected:
            with self.subTest(addition=addition):
                self.assertTrue(
                    VALIDATOR.semantic_contract_violations(
                        self.skill + "\n" + addition,
                        self.references,
                        self.ui,
                    ),
                    addition,
                )

        accepted = (
            "No content failure may authorize Terra fallback.",
            "Neither the manifest nor a probe establishes the effective native route.",
            "App tasks are not opt-out and require explicit current-request authorization.",
            "A timeout is not a sufficient reason to attempt Terra.",
            "Offline validation does not guarantee native runtime behavior.",
            "This Skill does not grant permissions.",
            "Neither content failures nor tool failures authorize Terra fallback.",
            "Content failures do not authorize Terra fallback and tool failures do not authorize Terra fallback.",
            "App tasks are not opt-out.",
            "App tasks are not opt-out. It may rain tomorrow.",
            "App tasks are not opt-out. They are documented.",
            "This Skill does not change the parent model.",
            "Content failures do not authorize Terra fallback.",
        )
        for addition in accepted:
            with self.subTest(addition=addition):
                self.assertEqual(
                    VALIDATOR.semantic_contract_violations(
                        self.skill + "\n" + addition,
                        self.references,
                        self.ui,
                    ),
                    [],
                )

        compound_contradictions = (
            "No content failure may authorize Terra fallback and tool failures may authorize Terra fallback.",
            "This Skill does not change the parent model and this Skill grants permissions.",
            "Offline validation does not guarantee native runtime behavior and offline validation will establish live runtime conformance.",
            "App tasks are not opt-out and App tasks may rely on implied authorization.",
        )
        for addition in compound_contradictions:
            with self.subTest(addition=addition):
                self.assertTrue(
                    VALIDATOR.semantic_contract_violations(
                        self.skill + "\n" + addition,
                        self.references,
                        self.ui,
                    ),
                    addition,
                )

        weakened = self.skill.replace(
            "only after explicit authorization in the current user request",
            "after authorization in the current user request",
        )
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.semantic_contract_violations(weakened, self.references, self.ui),
                [],
            )

    def test_connector_locality_and_pronoun_carryover(self) -> None:
        rejected = (
            "App tasks are not opt-out, and they inherit authorization from prior requests.",
            "App tasks are not opt-out whereas previous approval carries forward.",
            "App tasks are not opt-out but default to authorization from previous requests.",
            "App tasks are not opt-out but creation can use earlier approval.",
            "No content failure may authorize Terra fallback, yet tool errors qualify as a reason to attempt Terra.",
            "This Skill does not grant permissions, or it confers permission.",
            "App tasks are not opt-out plus previous approval carries forward.",
            "No content failure may authorize Terra fallback, tool errors qualify as a reason to attempt Terra.",
            "No content failure may authorize Terra fallback plus tool errors qualify as a reason to attempt Terra.",
            "This Skill does not grant permissions, or confers permission.",
            "This Skill does not grant permissions, plus it confers permission.",
            "App tasks are not opt-out, and rely on authorization from prior requests.",
            "App tasks are not opt-out. They inherit authorization from prior requests.",
            "App tasks are not opt-out, although those tasks can rely on prior authorization.",
            "App tasks are not opt-out. Such tasks are authorized by prior requests.",
            "App tasks are not opt-out. Such tasks are created by default.",
            "App tasks are not opt-out. They require no current-request authorization.",
            "App tasks are not opt-out. They accept prior request authorization.",
            "Content failures do not authorize Terra fallback, but tool failures do.",
            "Content failures do not authorize Terra fallback. Such outcomes are sufficient reasons for Terra.",
            "Content failures do not authorize Terra fallback. Such outcomes trigger Terra.",
            "The manifest does not prove the effective route. It demonstrates the effective route.",
            "The manifest does not prove the effective route, while the probe does.",
        )
        for addition in rejected:
            with self.subTest(addition=addition):
                self.assertTrue(
                    VALIDATOR.semantic_contract_violations(
                        self.skill + "\n" + addition,
                        self.references,
                        self.ui,
                    )
                )

        accepted = (
            "App tasks are not opt-out.",
            "No content failure may authorize Terra fallback.",
            "This Skill does not grant permissions.",
            "Content failures do not authorize Terra fallback and tool failures do not authorize Terra fallback.",
            "This Skill does not change the parent model or permissions, guarantee model availability, or perform automatic CLI fallback.",
            "App tasks are not opt-out. They do not inherit authorization from prior requests.",
            "Content failures do not authorize Terra fallback. Tool failures do not authorize Terra fallback.",
            "The manifest does not prove the effective route. The probe does not prove the effective route.",
            "App tasks are not opt-out. The weather is clear.",
            "App tasks are not opt-out. They are documented. They inherit authorization from prior requests.",
            "App tasks are not opt-out. Such tasks are documented in the authorization appendix.",
            "App tasks are not opt-out. They are documented in the authorization appendix.",
            "App tasks are not opt-out.\n\nSuch tasks are created by default.",
        )
        for addition in accepted:
            with self.subTest(addition=addition):
                self.assertEqual(
                    VALIDATOR.semantic_contract_violations(
                        self.skill + "\n" + addition,
                        self.references,
                        self.ui,
                    ),
                    [],
                )

    def test_semantic_rendered_masking_and_linear_connector_chain(self) -> None:
        hidden = (
            "```text\nApp tasks may be created by default.\nApp tasks are opt-out rather than opt-in.\n```",
            "`App tasks may be created by default.`",
            "<!-- App tasks are opt-out rather than opt-in. -->",
            "<!--\nApp tasks may be created by default.\nApp tasks are opt-out rather than opt-in.\n-->",
            r"\\`App tasks may be created by default.\\`",
        )
        for addition in hidden:
            with self.subTest(hidden=addition):
                self.assertEqual(
                    VALIDATOR.semantic_contract_violations(
                        self.skill + "\n" + addition,
                        self.references,
                        self.ui,
                    ),
                    [],
                )

        escaped_visible = r"\`App tasks are opt-out rather than opt-in.\`"
        self.assertTrue(
            VALIDATOR.semantic_contract_violations(
                self.skill + "\n" + escaped_visible,
                self.references,
                self.ui,
            )
        )

        rendered_unsafe = "ordinary paragraph\n    App tasks may be created by default."
        self.assertTrue(
            VALIDATOR.semantic_contract_violations(
                self.skill + "\n" + rendered_unsafe,
                self.references,
                self.ui,
            )
        )
        indented_code = "ordinary paragraph\n\n    App tasks may be created by default."
        self.assertEqual(
            VALIDATOR.semantic_contract_violations(
                self.skill + "\n" + indented_code,
                self.references,
                self.ui,
            ),
            [],
        )

        policy = next(
            item
            for item in VALIDATOR.SENSITIVE_CONTRACT_POLICIES
            if item.label == "Failure-to-Terra/fallback policy is ambiguous or unsafe"
        )

        def connector_chain(size: int) -> str:
            return "Content failures do not authorize Terra fallback" + (
                ", tool failures do not authorize Terra fallback" * size
            )

        short_fragments = VALIDATOR._contract_sensitive_fragments(
            connector_chain(64), policy
        )
        long_fragments = VALIDATOR._contract_sensitive_fragments(
            connector_chain(128), policy
        )
        self.assertLessEqual(len(long_fragments), 2 * len(short_fragments) + 4)
        validator_source = VALIDATOR_PATH.read_text(encoding="utf-8")
        self.assertNotIn("clause[boundary.end() :]", validator_source)
        self.assertNotIn("clause[: boundary.start()]", validator_source)

    def test_list_dialect_lazy_and_marker_boundaries_fail_closed(self) -> None:
        lazy_link = "- item\nlazy continuation line\n    [Nested](model-routing.md)\n"
        lazy_scan = VALIDATOR._scan_rendered_markdown_details(lazy_link)
        self.assertIn("model-routing.md", lazy_scan.targets)
        self.assertTrue(any("lazy list continuation" in item for item in lazy_scan.diagnostics))
        lazy_map = dict(self.references)
        lazy_map["workflow.md"] += lazy_link
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(self.skill, lazy_map, SKILL_PATH),
                [],
            )

        paragraph_link = "ordinary paragraph\n    [Nested](model-routing.md)\n"
        paragraph_scan = VALIDATOR._scan_rendered_markdown_details(paragraph_link)
        self.assertIn("model-routing.md", paragraph_scan.targets)
        paragraph_map = dict(self.references)
        paragraph_map["workflow.md"] += paragraph_link
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(
                    self.skill, paragraph_map, SKILL_PATH
                ),
                [],
            )

        list_blank_link = "- item\n\n    [Nested](model-routing.md)\n"
        list_blank_scan = VALIDATOR._scan_rendered_markdown_details(list_blank_link)
        self.assertIn("model-routing.md", list_blank_scan.targets)
        list_blank_map = dict(self.references)
        list_blank_map["workflow.md"] += list_blank_link
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(
                    self.skill, list_blank_map, SKILL_PATH
                ),
                [],
            )

        packet = self.references["task-contract.md"]
        lazy_heading = packet + "\n- item\nlazy continuation line\n    ## Extra\n"
        self.assertTrue(VALIDATOR.task_contract_violations(lazy_heading))

        overspaced = "-     [Nested](model-routing.md)\n"
        overspaced_scan = VALIDATOR._scan_rendered_markdown_details(overspaced)
        self.assertEqual(overspaced_scan.targets, [])
        self.assertTrue(any("more than four spaces" in item for item in overspaced_scan.diagnostics))
        self.assertTrue(
            VALIDATOR.task_contract_violations(packet + "\n-     ## Extra\n")
        )

        long_ordered = "1234567890. [Nested](model-routing.md)\n"
        long_ordered_scan = VALIDATOR._scan_rendered_markdown_details(long_ordered)
        self.assertTrue(any("more than nine digits" in item for item in long_ordered_scan.diagnostics))
        self.assertTrue(
            VALIDATOR.task_contract_violations(packet + "\n1234567890. ## Extra\n")
        )

        interrupted = "paragraph text\n2. [Nested](model-routing.md)\n"
        interrupted_scan = VALIDATOR._scan_rendered_markdown_details(interrupted)
        self.assertTrue(
            any("cannot interrupt a paragraph" in item for item in interrupted_scan.diagnostics)
        )
        self.assertTrue(
            VALIDATOR.task_contract_violations(packet + "\nparagraph text\n2. ## Extra\n")
        )

        self.assertEqual(
            VALIDATOR.extract_local_markdown_targets("1. [Nested](model-routing.md)\n"),
            ["model-routing.md"],
        )
        self.assertEqual(
            VALIDATOR.extract_local_markdown_targets(
                "- item\n  - nested\n    [Nested](model-routing.md)\n"
            ),
            ["model-routing.md"],
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

        reference_style_skill = self.skill.replace(
            "[references/model-routing.md](references/model-routing.md)",
            "[model routing][model-routing-ref]",
        )
        reference_style_skill += "\n[model-routing-ref]: references/model-routing.md\n"
        self.assertEqual(
            VALIDATOR.reference_topology_violations(reference_style_skill, self.references, SKILL_PATH),
            [],
        )

        required_links = "\n".join(
            f"[label-{name}](references/{name})" for name in sorted(REQUIRED_REFERENCES)
        )
        fenced_only_links = re.sub(
            r"\[[^\]]+\]\(\s*(?:<[^>]+>|[^\s)]+)\)",
            "",
            self.skill,
        ) + "\n```markdown\n" + required_links + "\n```\n"
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(fenced_only_links, self.references, SKILL_PATH),
                [],
            )

        image_only_links = re.sub(
            r"\[[^\]]+\]\(\s*(?:<[^>]+>|[^\s)]+)\)",
            "",
            self.skill,
        ) + "\n" + "\n".join(
            f"![alt-{name}](references/{name})" for name in sorted(REQUIRED_REFERENCES)
        )
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(image_only_links, self.references, SKILL_PATH),
                [],
            )

        shortcut_definitions = "\n".join(
            f"[shortcut-{name}]: references/{name}" for name in sorted(REQUIRED_REFERENCES)
        )
        shortcut_usages = "\n".join(f"[shortcut-{name}]" for name in sorted(REQUIRED_REFERENCES))
        shortcut_skill = re.sub(
            r"\[[^\]]+\]\(\s*(?:<[^>]+>|[^\s)]+)\)",
            "",
            self.skill,
        ) + "\n" + shortcut_definitions + "\n" + shortcut_usages
        self.assertEqual(
            VALIDATOR.reference_topology_violations(shortcut_skill, self.references, SKILL_PATH),
            [],
        )

        fenced_reference_map = dict(self.references)
        fenced_reference_map["workflow.md"] += "\n```markdown\n[Nested](model-routing.md)\n```\n"
        self.assertEqual(
            VALIDATOR.reference_topology_violations(self.skill, fenced_reference_map, SKILL_PATH),
            [],
        )

        malformed_brackets = "[" * 100_000
        self.assertEqual(VALIDATOR.extract_local_markdown_targets(malformed_brackets), [])
        self.assertEqual(VALIDATOR.extract_local_markdown_targets("[" * 200_000), [])
        validator_source = VALIDATOR_PATH.read_text(encoding="utf-8")
        self.assertNotIn("INLINE_MARKDOWN_LINK_RE", validator_source)
        self.assertNotIn("REFERENCE_USAGE_RE", validator_source)

        duplicate_reference_map = dict(self.references)
        duplicate_reference_map["workflow.md"] += (
            "\n[route]: references/model-routing.md\n"
            "[route]: https://example.com/model-routing.md\n"
            "[Routing][route]\n"
        )
        duplicate_scan = VALIDATOR._scan_rendered_markdown_details(
            duplicate_reference_map["workflow.md"]
        )
        self.assertIn("references/model-routing.md", duplicate_scan.targets)
        self.assertTrue(any("duplicate reference definition" in item for item in duplicate_scan.diagnostics))
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(self.skill, duplicate_reference_map, SKILL_PATH),
                [],
            )

        indented_only_links = re.sub(
            r"\[[^\]]+\]\(\s*(?:<[^>]+>|[^\s)]+)\)",
            "",
            self.skill,
        ) + "\n" + "\n".join(
            f"    [indented-{name}](references/{name})" for name in sorted(REQUIRED_REFERENCES)
        )
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(indented_only_links, self.references, SKILL_PATH),
                [],
            )
        tab_indented = "\n".join(
            f"\t[tab-{name}](references/{name})" for name in sorted(REQUIRED_REFERENCES)
        )
        self.assertEqual(VALIDATOR.extract_local_markdown_targets(tab_indented), [])

        escaped_image_map = dict(self.references)
        escaped_image_map["workflow.md"] += r"\![escaped](model-routing.md)" + "\n"
        self.assertEqual(
            VALIDATOR.extract_local_markdown_targets(r"\![escaped](model-routing.md)"),
            ["model-routing.md"],
        )
        self.assertEqual(
            VALIDATOR.extract_local_markdown_targets(r"\\![even-slash](model-routing.md)"),
            [],
        )
        self.assertEqual(
            VALIDATOR.extract_local_markdown_targets(r"\\\![odd-slash](model-routing.md)"),
            ["model-routing.md"],
        )
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(self.skill, escaped_image_map, SKILL_PATH),
                [],
            )

        escaped_label_cases = (
            r"[label with \] literal](model-routing.md)",
            r"[label with \[ literal](model-routing.md)",
        )
        for escaped_label in escaped_label_cases:
            with self.subTest(escaped_label=escaped_label):
                escaped_label_scan = VALIDATOR._scan_rendered_markdown_details(escaped_label)
                self.assertIn("model-routing.md", escaped_label_scan.targets)
                self.assertFalse(
                    any("nested bracket label" in item for item in escaped_label_scan.diagnostics)
                )
        escaped_label_map = dict(self.references)
        escaped_label_map["workflow.md"] += "\n" + "\n".join(escaped_label_cases)
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(self.skill, escaped_label_map, SKILL_PATH),
                [],
            )

        escaped_backtick = r"\` [escaped](model-routing.md) \`"
        self.assertEqual(
            VALIDATOR.extract_local_markdown_targets(escaped_backtick),
            ["model-routing.md"],
        )
        escaped_backtick_map = dict(self.references)
        escaped_backtick_map["workflow.md"] += escaped_backtick + "\n"
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(self.skill, escaped_backtick_map, SKILL_PATH),
                [],
            )

        soft_break = "[Outer\n[Inner](model-routing.md)](workflow.md)"
        soft_break_scan = VALIDATOR._scan_rendered_markdown_details(soft_break)
        self.assertIn("model-routing.md", soft_break_scan.targets)
        self.assertTrue(any("nested bracket label" in item for item in soft_break_scan.diagnostics))
        soft_break_map = dict(self.references)
        soft_break_map["workflow.md"] += soft_break + "\n"
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(self.skill, soft_break_map, SKILL_PATH),
                [],
            )

        list_container = "- item\n    [nested](model-routing.md)\n"
        self.assertEqual(
            VALIDATOR.extract_local_markdown_targets(list_container),
            ["model-routing.md"],
        )
        self.assertEqual(
            VALIDATOR.extract_local_markdown_targets("    [top-level-code](model-routing.md)\n"),
            [],
        )
        list_container_map = dict(self.references)
        list_container_map["workflow.md"] += list_container
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(self.skill, list_container_map, SKILL_PATH),
                [],
            )

        nested_container_links = (
            "- item\n  - nested\n    [Nested](model-routing.md)\n",
            "100. item\n     2. nested\n        [Nested](model-routing.md)\n",
            "10. item\n    100. nested\n         [Nested](model-routing.md)\n",
            "- item\n    - nested\n        [Nested](model-routing.md)\n",
            "- item\n    1. nested\n        [Nested](model-routing.md)\n",
            "- item\n    - nested\n        > [Nested](model-routing.md)\n",
            "- item\n    1. nested\n        - deeper\n            [Nested](model-routing.md)\n",
        )
        for nested_links in nested_container_links:
            with self.subTest(nested_links=nested_links):
                self.assertEqual(
                    VALIDATOR.extract_local_markdown_targets(nested_links),
                    ["model-routing.md"],
                )
                nested_map = dict(self.references)
                nested_map["workflow.md"] += nested_links
                with self.assertRaises(AssertionError):
                    self.assertEqual(
                        VALIDATOR.reference_topology_violations(self.skill, nested_map, SKILL_PATH),
                        [],
                    )

        ambiguous_list = "10. item\n  - ambiguous\n    [Nested](model-routing.md)\n"
        ambiguous_scan = VALIDATOR._scan_rendered_markdown_details(ambiguous_list)
        self.assertTrue(any("ambiguous list" in item for item in ambiguous_scan.diagnostics))
        ambiguous_map = dict(self.references)
        ambiguous_map["workflow.md"] += ambiguous_list
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(self.skill, ambiguous_map, SKILL_PATH),
                [],
            )

        deep_blockquote = "> " * 17 + "[Nested](model-routing.md)\n"
        deep_scan = VALIDATOR._scan_rendered_markdown_details(deep_blockquote)
        self.assertTrue(any("container prefix depth exceeded" in item for item in deep_scan.diagnostics))
        deep_map = dict(self.references)
        deep_map["workflow.md"] += deep_blockquote
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(self.skill, deep_map, SKILL_PATH),
                [],
            )

        percent_encoded = "[nested](./model-routing%2Emd?x=1#y)"
        self.assertEqual(
            VALIDATOR.extract_local_markdown_targets(percent_encoded),
            ["model-routing.md"],
        )
        percent_map = dict(self.references)
        percent_map["workflow.md"] += percent_encoded + "\n"
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(self.skill, percent_map, SKILL_PATH),
                [],
            )

        entity_encoded = "[nested](model-routing&amp;#46;md)"
        self.assertEqual(
            VALIDATOR.extract_local_markdown_targets(entity_encoded),
            ["model-routing.md"],
        )
        entity_map = dict(self.references)
        entity_map["workflow.md"] += entity_encoded + "\n"
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(self.skill, entity_map, SKILL_PATH),
                [],
            )

        raw_html_map = dict(self.references)
        raw_html_map["workflow.md"] += '<a href="model-routing.md">nested</a>\n'
        raw_html_scan = VALIDATOR._scan_rendered_markdown_details(raw_html_map["workflow.md"])
        self.assertTrue(any("raw HTML link" in item for item in raw_html_scan.diagnostics))
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(self.skill, raw_html_map, SKILL_PATH),
                [],
            )
        multiline_raw_html = '<a\n href="model-routing.md">nested</a>\n'
        multiline_raw_scan = VALIDATOR._scan_rendered_markdown_details(multiline_raw_html)
        self.assertTrue(any("raw HTML link" in item for item in multiline_raw_scan.diagnostics))
        multiline_raw_html_indented = '<a\n    href="model-routing.md">nested</a>\n'
        self.assertTrue(
            any(
                "raw HTML link" in item
                for item in VALIDATOR._scan_rendered_markdown_details(
                    multiline_raw_html_indented
                ).diagnostics
            )
        )
        uppercase_raw_html = '<A\n HREF="model-routing.md">nested</A>\n'
        self.assertTrue(
            any(
                "raw HTML link" in item
                for item in VALIDATOR._scan_rendered_markdown_details(uppercase_raw_html).diagnostics
            )
        )
        multiline_raw_map = dict(self.references)
        multiline_raw_map["workflow.md"] += multiline_raw_html_indented
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(self.skill, multiline_raw_map, SKILL_PATH),
                [],
            )
        inline_code_html = "`<h2 id=\"extra\">ignored</h2>`\n"
        self.assertEqual(
            VALIDATOR._scan_rendered_markdown_details(inline_code_html).diagnostics,
            [],
        )
        comment_html = "<!-- <h2 id=\"extra\">ignored</h2> -->\n<!--\n<a href=\"model-routing.md\">ignored</a>\n-->\n"
        self.assertEqual(
            VALIDATOR._scan_rendered_markdown_details(comment_html).diagnostics,
            [],
        )
        escaped_anchor = r'\<a href="model-routing.md">escaped'
        self.assertEqual(
            VALIDATOR._scan_rendered_markdown_details(escaped_anchor).diagnostics,
            [],
        )
        even_escaped_anchor = r'\\<a href="model-routing.md">interpreted'
        self.assertTrue(
            any(
                "raw HTML link" in item
                for item in VALIDATOR._scan_rendered_markdown_details(even_escaped_anchor).diagnostics
            )
        )
        self.assertEqual(
            VALIDATOR._scan_rendered_markdown_details("```markdown\n<a\n href=\"model-routing.md\">\n```\n").diagnostics,
            [],
        )
        self.assertEqual(
            VALIDATOR._scan_rendered_markdown_details('    <a\n href="model-routing.md">\n').diagnostics,
            [],
        )
        self.assertEqual(
            VALIDATOR._scan_rendered_markdown_details("safe text: 2 < 3 and <angle>").diagnostics,
            [],
        )
        self.assertEqual(
            VALIDATOR._scan_rendered_markdown_details('    <a href="model-routing.md">code</a>').diagnostics,
            [],
        )

        titled = VALIDATOR._scan_rendered_markdown_details("[nested](model-routing.md \"title\")")
        self.assertTrue(any("whitespace-invalid" in item for item in titled.diagnostics))

        malformed_destinations = (
            "[bad](foo bar)",
            "[bad](foo(bar)",
            "[bad](<foo)",
            "[bad](<foo bar>)",
            "[bad](<foo> title)",
        )
        for malformed in malformed_destinations:
            with self.subTest(malformed=malformed):
                malformed_scan = VALIDATOR._scan_rendered_markdown_details(malformed)
                self.assertTrue(malformed_scan.diagnostics)
        malformed_definitions = (
            "[bad-paren]: foo(bar\n",
            "[bad-angle]: <foo\n",
            "[bad-space]: foo bar\n",
            "[bad-angle-space]: <foo bar>\n",
        )
        malformed_definition_scan = VALIDATOR._scan_rendered_markdown_details(
            "".join(malformed_definitions)
        )
        self.assertGreaterEqual(len(malformed_definition_scan.diagnostics), 3)
        malformed_reference_map = dict(self.references)
        malformed_reference_map["workflow.md"] += "".join(malformed_definitions)
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(self.skill, malformed_reference_map, SKILL_PATH),
                [],
            )

        image_map = dict(self.references)
        image_map["workflow.md"] += "![image](model-routing.md)\n"
        self.assertEqual(VALIDATOR.extract_local_markdown_targets("![image](model-routing.md)"), [])
        self.assertEqual(
            VALIDATOR.reference_topology_violations(self.skill, image_map, SKILL_PATH),
            [],
        )

        invalid_fence_map = dict(self.references)
        invalid_fence_map["workflow.md"] += "```bad` info\n[Nested](model-routing.md)\n"
        invalid_scan = VALIDATOR._scan_rendered_markdown_details(invalid_fence_map["workflow.md"])
        self.assertIn("model-routing.md", invalid_scan.targets)
        self.assertTrue(any("invalid backtick fence opener" in item for item in invalid_scan.diagnostics))
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(self.skill, invalid_fence_map, SKILL_PATH),
                [],
            )

        invalid_fenced_skill = re.sub(
            r"\[[^\]]+\]\(\s*(?:<[^>]+>|[^\s)]+)\)",
            "",
            self.skill,
        ) + "\n```bad` info\n" + required_links + "\n"
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(invalid_fenced_skill, self.references, SKILL_PATH),
                [],
            )

        nested_label_map = dict(self.references)
        nested_label_map["workflow.md"] += "\n[Outer [Inner](model-routing.md)](workflow.md)\n"
        nested_scan = VALIDATOR._scan_rendered_markdown_details(nested_label_map["workflow.md"])
        self.assertTrue(any("nested bracket label" in item for item in nested_scan.diagnostics))
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(self.skill, nested_label_map, SKILL_PATH),
                [],
            )

        unequal_backticks_map = dict(self.references)
        unequal_backticks_map["workflow.md"] += "\n`broken [Nested](model-routing.md)``\n"
        unequal_scan = VALIDATOR._scan_rendered_markdown_details(unequal_backticks_map["workflow.md"])
        self.assertTrue(any("inline backtick" in item for item in unequal_scan.diagnostics))
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(self.skill, unequal_backticks_map, SKILL_PATH),
                [],
            )

        unused_definitions = "\n".join(
            f"[unused-{name}]: references/{name}" for name in sorted(REQUIRED_REFERENCES)
        )
        without_rendered_links = re.sub(
            r"\[[^\]]+\]\(\s*(?:<[^>]+>|[^\s)]+)\)",
            "",
            self.skill,
        ) + "\n" + unused_definitions
        with self.assertRaises(AssertionError):
            self.assertEqual(
                VALIDATOR.reference_topology_violations(without_rendered_links, self.references, SKILL_PATH),
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
        fenced_fake = packet.replace(
            "## 3. Inputs/evidence",
            "```markdown\n## 3. Inputs/evidence\n```\n#### Rendered fake",
        )
        with self.assertRaises(AssertionError):
            self.assertEqual(VALIDATOR.task_contract_violations(fenced_fake), [])
        fenced_examples = packet + (
            "\n```markdown\n## 99. Fake\nFake text\n---\n```\n"
            "````markdown\n## 98. Fake\nFake text\n===\n`````\n"
            "~~~~markdown\n### 99. Fake\nFake text\n===\n~~~~~\n"
        )
        self.assertEqual(VALIDATOR.task_contract_violations(fenced_examples), [])
        self.assertEqual(
            VALIDATOR.task_contract_violations(packet + "\n- ordinary packet detail\n"),
            [],
        )
        root_code_packet = packet + "\n# Code example follows\n\n"
        self.assertEqual(
            VALIDATOR.task_contract_violations(
                root_code_packet + "    ### Indented code heading\n"
            ),
            [],
        )
        self.assertEqual(
            VALIDATOR.task_contract_violations(packet + "\n# H1 remains outside the packet contract\n"),
            [],
        )
        self.assertEqual(
            VALIDATOR.task_contract_violations(
                root_code_packet + "    indented code candidate\n---\n"
            ),
            [],
        )
        for bare_heading in ("##", "###", "####", "#####", "######"):
            with self.subTest(bare_heading=bare_heading), self.assertRaises(AssertionError):
                self.assertEqual(
                    VALIDATOR.task_contract_violations(packet + f"\n{bare_heading}\n"),
                    [],
                )
        container_heading_mutations = (
            "> ## Extra\n",
            "> ### Extra\n",
            "> Heading\n> ---\n",
            "- item\n    ## Extra\n",
            "- item\n    ### Extra\n",
            "- item\n    Heading\n    ---\n",
            "- > ## Extra\n",
            "- > ### Extra\n",
            "- 1. ## Extra\n",
            "- 1. ### Extra\n",
            "> - > ## Extra\n",
            "- > Heading\n  > ---\n",
            "- item\n    - nested\n        ## Extra\n",
            "- item\n  - nested\n    ## Extra\n",
            "- item\n    1. nested\n        ### Extra\n",
            "- item\n    - nested\n        > ## Extra\n",
        )
        for mutation in container_heading_mutations:
            with self.subTest(container_heading=mutation), self.assertRaises(AssertionError):
                self.assertEqual(
                    VALIDATOR.task_contract_violations(packet + "\n" + mutation),
                    [],
                )
        closed_hash_packet = re.sub(
            r"(?m)^(## (?:1\. Objective|2\. Ownership|3\. Inputs/evidence|4\. Constraints/requirements|5\. Verification/handoff))$",
            r"\1 ##",
            packet,
        )
        self.assertEqual(VALIDATOR.task_contract_violations(closed_hash_packet), [])
        self.assertTrue(
            VALIDATOR.task_contract_violations(packet + "\n<h2>Extra</h2>\n")
        )
        multiline_raw_heading = packet + '\n<h2\n id="extra">Extra</h2>\n'
        self.assertTrue(VALIDATOR.task_contract_violations(multiline_raw_heading))
        multiline_raw_heading_indented = packet + '\n<h2\n    id="extra">Extra</h2>\n'
        self.assertTrue(VALIDATOR.task_contract_violations(multiline_raw_heading_indented))
        self.assertEqual(
            VALIDATOR.task_contract_violations("```markdown\n<h2\n id=\"extra\">\n```\n" + packet),
            [],
        )
        self.assertEqual(
            VALIDATOR.task_contract_violations(packet + '\n`<h2 id="extra">ignored</h2>`\n'),
            [],
        )
        self.assertEqual(
            VALIDATOR.task_contract_violations(packet + '\n<!--\n<h2 id="extra">ignored</h2>\n-->\n'),
            [],
        )
        self.assertEqual(
            VALIDATOR.task_contract_violations(packet + "\nordinary text: 2 < 3\n"),
            [],
        )
        self.assertEqual(
            VALIDATOR.task_contract_violations(
                root_code_packet + "    <h2>code example</h2>\n"
            ),
            [],
        )

        unclosed = packet + "\n```markdown\n## Extra\n"
        unfenced_lines, unclosed_fence = VALIDATOR._unfenced_lines(unclosed)
        self.assertTrue(unclosed_fence)
        self.assertNotIn("## Extra", unfenced_lines)
        with self.assertRaises(AssertionError):
            self.assertEqual(VALIDATOR.task_contract_violations(unclosed), [])

        mismatched_unclosed = packet + "\n~~~~markdown\n## Extra\n```\n"
        with self.assertRaises(AssertionError):
            self.assertEqual(VALIDATOR.task_contract_violations(mismatched_unclosed), [])

        invalid_fence_heading = packet + "\n```bad` info\n### Rendered H3\n"
        with self.assertRaises(AssertionError):
            self.assertEqual(VALIDATOR.task_contract_violations(invalid_fence_heading), [])

        deep_heading = packet + "\n" + "> " * 17 + "## Extra\n"
        with self.assertRaises(AssertionError):
            self.assertEqual(VALIDATOR.task_contract_violations(deep_heading), [])


if __name__ == "__main__":
    unittest.main()
