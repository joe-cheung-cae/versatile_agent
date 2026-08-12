#!/usr/bin/env python3
"""Focused offline tests for the registered versatile-dev source contract."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "payload/skills/versatile-dev/SKILL.md"
UI_PATH = ROOT / "payload/skills/versatile-dev/agents/openai.yaml"
REFERENCE_DIR = ROOT / "payload/skills/versatile-dev/references"
VALIDATOR_PATH = ROOT / "scripts/validate_bundle.py"
SPEC = importlib.util.spec_from_file_location("validate_bundle_skill_contract", VALIDATOR_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to load validator: {VALIDATOR_PATH}")
VALIDATOR = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = VALIDATOR
SPEC.loader.exec_module(VALIDATOR)


def mutated(text: str, old: str, new: str) -> str:
    if old not in text:
        raise AssertionError(f"mutation anchor is absent: {old!r}")
    return text.replace(old, new, 1)


class SkillContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.skill = SKILL_PATH.read_text(encoding="utf-8")
        cls.ui = UI_PATH.read_text(encoding="utf-8")
        cls.references = {
            path.name: path.read_text(encoding="utf-8")
            for path in REFERENCE_DIR.glob("*.md")
        }
        cls.task = cls.references["task-contract.md"]
        cls.routing = cls.references["model-routing.md"]

    def assert_semantic_rejects(self, skill: str, references: dict[str, str] | None = None, ui: str | None = None) -> None:
        errors = VALIDATOR.semantic_contract_violations(skill, references or self.references, ui or self.ui)
        self.assertTrue(errors, "the semantic mutation was accepted")

    def assert_topology_rejects(self, skill: str, references: dict[str, str] | None = None) -> None:
        errors = VALIDATOR.reference_topology_violations(skill, references or self.references, SKILL_PATH)
        self.assertTrue(errors, "the topology mutation was accepted")

    def test_real_tree_is_valid(self) -> None:
        self.assertEqual(VALIDATOR.semantic_contract_violations(self.skill, self.references, self.ui), [])
        self.assertEqual(VALIDATOR.reference_topology_violations(self.skill, self.references, SKILL_PATH), [])
        self.assertEqual(VALIDATOR.task_contract_violations(self.task), [])

    def test_frontmatter_trigger_boundaries_and_prompt(self) -> None:
        block, errors = VALIDATOR._frontmatter(self.skill)
        self.assertEqual(errors, [])
        self.assertIn("non-trivial repository engineering", block or "")
        self.assertIn("Do not use for simple Q&A or status-only work", block or "")
        self.assertIn("$versatile-dev", self.ui)
        self.assertTrue(VALIDATOR.openai_yaml_violations(self.ui) == [])
        self.assert_semantic_rejects(self.skill.replace("mapping, planning", "mapping"))

    def test_registered_skill_block_is_complete_and_active(self) -> None:
        for clause in VALIDATOR.CANONICAL_BLOCKS["SKILL.md"][2]:
            self.assert_semantic_rejects(mutated(self.skill, clause, ""))
            self.assert_semantic_rejects(mutated(self.skill, clause, clause + "\n" + clause))
            self.assert_semantic_rejects(mutated(self.skill, clause, "    " + clause))
        self.assert_semantic_rejects(mutated(self.skill, "## Contract", "## Other section"))
        self.assert_semantic_rejects(mutated(self.skill, "Lead owns user intent", "`Lead owns user intent"))
        fenced = mutated(self.skill, "Lead owns user intent", "```\nLead owns user intent")
        self.assert_semantic_rejects(fenced)

    def test_canonical_section_must_be_active_unique_and_closed(self) -> None:
        section = VALIDATOR.CANONICAL_SECTIONS["SKILL.md"]
        fenced_section = mutated(self.skill, section, "```\n" + section + "\n```")
        commented_section = mutated(self.skill, section, "<!--\n" + section + "\n-->")
        duplicated_section = mutated(self.skill, section, section + "\n" + section)
        for candidate in (fenced_section, commented_section, duplicated_section):
            self.assert_semantic_rejects(candidate)

        begin = VALIDATOR.CANONICAL_BLOCKS["SKILL.md"][0]
        for unsafe in (
            "- > App tasks may be created by default.",
            "App tasks may use workspace approval instead.",
        ):
            candidate = mutated(self.skill, begin, begin + "\n" + unsafe)
            self.assert_semantic_rejects(candidate)

    def test_registered_routing_block_is_complete(self) -> None:
        for clause in VALIDATOR.CANONICAL_BLOCKS["model-routing.md"][2]:
            references = dict(self.references)
            references["model-routing.md"] = mutated(self.routing, clause, "")
            self.assert_semantic_rejects(self.skill, references)
        references = dict(self.references)
        references["model-routing.md"] = mutated(self.routing, "## Canonical routing contract", "## Other section")
        self.assert_semantic_rejects(self.skill, references)
        references["model-routing.md"] = mutated(self.routing, "Content, tool, task", "```\nContent, tool, task")
        self.assert_semantic_rejects(self.skill, references)

    def test_direct_links_are_exact_once_and_active(self) -> None:
        self.assertEqual(
            VALIDATOR.reference_topology_violations(self.skill, self.references, SKILL_PATH),
            [],
        )
        for target, source in VALIDATOR.DIRECT_LINK_LINES.items():
            self.assertEqual(self.skill.splitlines().count(source), 1, target)
            self.assert_topology_rejects(mutated(self.skill, source, "    " + source))
            self.assert_topology_rejects(mutated(self.skill, source, "```\n" + source + "\n```"))
        removed = self.skill
        for source in VALIDATOR.DIRECT_LINK_LINES.values():
            removed = removed.replace(source, "")
        definitions = "\n".join(f"[unused-{i}]: {target}" for i, target in enumerate(VALIDATOR.DIRECT_LINK_LINES))
        self.assert_topology_rejects(removed + "\n" + definitions)

    def test_unsupported_skill_link_forms_fail_closed(self) -> None:
        cases = (
            "[extra](references/model-routing.md)",
            "[extra][routing]",
            "[routing]: references/model-routing.md",
            '<a href="references/model-routing.md">extra</a>',
            "[extra](references/model-routing%2Emd)",
            r"[extra](references\\model-routing.md)",
            "[extra](references/model-routing.md?x=1#y)",
            "[extra](references/\nmodel-routing.md)",
            "- [extra](references/model-routing.md)",
            "<!-- [extra](references/model-routing.md) -->",
        )
        for case in cases:
            self.assert_topology_rejects(self.skill + "\n" + case)

    def test_reference_links_allow_fragments_and_external_only(self) -> None:
        references = dict(self.references)
        references["workflow.md"] += "\n[local state](#state-model)\n[external](https://example.com)\n"
        self.assertEqual(VALIDATOR.reference_topology_violations(self.skill, references, SKILL_PATH), [])
        for bad in (
            "[nested](model-routing.md)",
            "[nested](model-routing.md?x=1#y)",
            "[nested][route]\n\n[route]: model-routing.md",
            '<a href="model-routing.md">nested</a>',
            "```\n[nested](model-routing.md)\n```",
            "<!-- [nested](model-routing.md) -->",
        ):
            bad_refs = dict(self.references)
            bad_refs["workflow.md"] += "\n" + bad
            self.assert_topology_rejects(self.skill, bad_refs)

    def test_task_contract_exact_topology_and_mutations(self) -> None:
        self.assertEqual(VALIDATOR.task_contract_violations(self.task), [])
        for heading in (
            "# Subagent task contract",
            "## 1. Objective",
            "## 2. Ownership",
            "## 3. Inputs/evidence",
            "## 4. Constraints/requirements",
            "## 5. Verification/handoff",
        ):
            self.assertTrue(VALIDATOR.task_contract_violations(mutated(self.task, heading, "")))
        for extra in (
            "# Extra",
            "## Extra",
            "### 6 Extra",
            "##",
            "## 1. Objective ##",
            "> ## Extra",
            "    ## Extra",
            "```\n## Extra\n```",
            "<h2>Extra</h2>",
            "Setext title\n---",
        ):
            self.assertTrue(VALIDATOR.task_contract_violations(self.task + "\n" + extra), extra)

    def test_task_contract_h1_and_h2_wrong_order_are_not_sentinels(self) -> None:
        wrong = self.task.replace("## 2. Ownership\n", "## 3. Inputs/evidence\n", 1)
        self.assertTrue(VALIDATOR.task_contract_violations(wrong))
        wrong = self.task.replace("## 5. Verification/handoff", "## 4. Constraints/requirements", 1)
        self.assertTrue(VALIDATOR.task_contract_violations(wrong))

    def test_openai_yaml_is_a_strict_closed_schema(self) -> None:
        self.assertEqual(VALIDATOR.openai_yaml_violations(self.ui), [])
        cases = (
            self.ui + "\n  extra: \"x\"",
            self.ui.replace("interface:\n", "interface:\ninterface:\n", 1),
            self.ui.replace('default_prompt: "', 'default_prompt: `', 1),
            self.ui.replace('default_prompt: "', 'default_prompt: "<!-- ', 1),
            self.ui.replace('default_prompt: "', 'default_prompt: |\n', 1),
            self.ui.replace("engineering work", "engineering drift", 1),
            self.ui.replace("$versatile-dev", "versatile-dev"),
        )
        for case in cases:
            self.assertTrue(VALIDATOR.openai_yaml_violations(case), repr(case))

    def test_stale_literals_and_prior_advisor_families_are_rejected(self) -> None:
        for stale in VALIDATOR.STALE_LITERALS:
            self.assert_semantic_rejects(self.skill + "\n" + stale)
        nested = self.skill + "\n- > ### Extra\n- 1. [nested](references/model-routing.md)"
        self.assert_topology_rejects(nested)
        alternate = mutated(
            self.skill,
            "Lead owns user intent",
            "Lead owns user intent\nApp tasks may use workspace approval instead",
        )
        self.assert_semantic_rejects(alternate)
        self.assert_semantic_rejects(self.skill, ui=self.ui.replace("accept the change.", "accept `the change.`"))

    def test_fragment_only_reference_controls_remain_legal(self) -> None:
        for filename in ("workflow.md", "review-policy.md"):
            self.assertEqual(
                VALIDATOR._reference_file_link_violations(filename, self.references[filename]),
                [],
            )
        self.assertFalse(VALIDATOR._external_or_fragment("model-routing.md"))
        self.assertTrue(VALIDATOR._external_or_fragment("#state-model"))
        self.assertTrue(VALIDATOR._external_or_fragment("mailto:test@example.com"))


if __name__ == "__main__":
    unittest.main()
