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
        frontmatter_close = f"description: {VALIDATOR.EXPECTED_DESCRIPTION}\n---\n"
        for inserted in ("  App tasks may be created by default.", "# comment", "", "extra: value"):
            candidate = self.skill.replace(
                frontmatter_close,
                f"description: {VALIDATOR.EXPECTED_DESCRIPTION}\n{inserted}\n---\n",
                1,
            )
            self.assert_semantic_rejects(candidate)

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

    def test_canonical_sections_are_unique_across_the_whole_document(self) -> None:
        skill_section = VALIDATOR.CANONICAL_SECTIONS["SKILL.md"]
        self.assert_semantic_rejects(self.skill + "\n" + skill_section + "\n")

        routing_section = VALIDATOR.CANONICAL_SECTIONS["model-routing.md"]
        references = dict(self.references)
        references["model-routing.md"] = self.routing + "\n" + routing_section + "\n"
        self.assert_semantic_rejects(self.skill, references)

        moved_skill = self.skill.replace(skill_section + "\n", "", 1)
        moved_skill = moved_skill.replace(
            VALIDATOR.CANONICAL_BLOCKS["SKILL.md"][0],
            VALIDATOR.CANONICAL_BLOCKS["SKILL.md"][0] + "\n" + skill_section,
            1,
        )
        self.assert_semantic_rejects(moved_skill)

    def test_canonical_block_stays_inside_its_designated_section(self) -> None:
        def block(text: str, filename: str) -> str:
            begin, end, _ = VALIDATOR.CANONICAL_BLOCKS[filename]
            lines = text.splitlines()
            start = lines.index(begin)
            finish = lines.index(end)
            return "\n".join(lines[start : finish + 1])

        skill_block = block(self.skill, "SKILL.md")
        moved_skill = self.skill.replace(skill_block + "\n", "", 1) + "\n" + skill_block + "\n"
        self.assert_semantic_rejects(moved_skill)
        self.assert_semantic_rejects(
            self.skill.replace("<!-- BEGIN versatile-dev canonical contract -->", "## Inserted peer\n<!-- BEGIN versatile-dev canonical contract -->", 1)
        )
        for peer in ("## Peer `code`", "# Peer `code`"):
            self.assert_semantic_rejects(
                self.skill.replace("## Contract\n", "## Contract\n" + peer + "\n", 1)
            )
            routing_candidate = self.routing.replace(
                "## Canonical routing contract\n",
                "## Canonical routing contract\n" + peer + "\n",
                1,
            )
            references = dict(self.references)
            references["model-routing.md"] = routing_candidate
            self.assert_semantic_rejects(self.skill, references)
        fenced_peer = self.skill.replace("## Contract\n", "## Contract\n```\n## Peer `code`\n```\n", 1)
        self.assertEqual(VALIDATOR.semantic_contract_violations(fenced_peer, self.references, self.ui), [])
        commented_peer = self.skill.replace("## Contract\n", "## Contract\n<!--\n## Peer `code`\n-->\n", 1)
        self.assert_semantic_rejects(commented_peer)
        empty_peers = ("#", "##", "#   ", "##\t")
        for peer in empty_peers:
            skill_candidate = self.skill.replace(
                "## Contract\n",
                "## Contract\n" + peer + "\n",
                1,
            )
            self.assert_semantic_rejects(skill_candidate)

            routing_candidate = self.routing.replace(
                "## Canonical routing contract\n",
                "## Canonical routing contract\n" + peer + "\n",
                1,
            )
            references = dict(self.references)
            references["model-routing.md"] = routing_candidate
            self.assert_semantic_rejects(self.skill, references)

        fenced_empty = self.skill.replace(
            "## Contract\n",
            "## Contract\n```\n##\n```\n",
            1,
        )
        self.assertEqual(VALIDATOR.semantic_contract_violations(fenced_empty, self.references, self.ui), [])
        self.assertEqual(VALIDATOR.canonical_block_violations("model-routing.md", self.routing), [])

        routing_block = block(self.routing, "model-routing.md")
        without_routing_block = self.routing.replace(routing_block + "\n", "", 1)
        moved_routing = without_routing_block.replace(
            "## 证据分层与 runtime record\n",
            "## 证据分层与 runtime record\n\n" + routing_block + "\n",
            1,
        )
        references = dict(self.references)
        references["model-routing.md"] = moved_routing
        self.assert_semantic_rejects(self.skill, references)

    def test_source_dialect_rejects_html_wrappers_and_angle_autolinks(self) -> None:
        begin = VALIDATOR.CANONICAL_BLOCKS["SKILL.md"][0]
        end = VALIDATOR.CANONICAL_BLOCKS["SKILL.md"][1]
        wrapped_block = self.skill.replace(begin, "<div>\n" + begin, 1).replace(end, end + "\n</div>", 1)
        self.assert_semantic_rejects(wrapped_block)

        wrapped_links = self.skill
        for source in VALIDATOR.DIRECT_LINK_LINES.values():
            wrapped_links = wrapped_links.replace(source, "<div>\n" + source + "\n</div>", 1)
        self.assert_topology_rejects(wrapped_links)

        for token in (
            "<file:model-routing.md>",
            "<javascript:alert(1)>",
            "<https://example.com>",
        ):
            references = dict(self.references)
            references["workflow.md"] += "\n" + token + "\n"
            self.assert_topology_rejects(self.skill, references)

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
        references["workflow.md"] += "\n[local state](#state-model)\n[http](http://example.com)\n[https](HTTPS://example.com)\n[mail](mailto:test@example.com)\n"
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
        for scheme in ("file:model-routing.md", "javascript:alert(1)", "data:text/plain,x", "gopher://example.com"):
            bad_refs = dict(self.references)
            bad_refs["workflow.md"] += f"\n[unsupported]({scheme})\n"
            self.assert_topology_rejects(self.skill, bad_refs)
            self.assertFalse(VALIDATOR._external_or_fragment(scheme))

    def test_task_contract_exact_topology_and_mutations(self) -> None:
        self.assertEqual(VALIDATOR.task_contract_violations(self.task), [])
        exact_failures = (
            "##\tExtra\n",
            "- > paragraph\n  >\n    > ## Extra\n",
            "> ```\n> ordinary\n> ```\n",
            "    ```\nordinary\n    ```\n",
            "> Extra\n> ---\n",
            "1) ## Extra\n",
            "1) > ## Extra\n",
            "- Extra\n    ---\n",
        )
        for suffix in exact_failures:
            self.assertTrue(VALIDATOR.task_contract_violations(self.task + "\n" + suffix), suffix)
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

    def test_source_flags_close_and_preserve_fences(self) -> None:
        for spaces in range(4):
            self.assertEqual(VALIDATOR._fence_start(" " * spaces + "```text"), ("`", 3))
            self.assertEqual(VALIDATOR._fence_start(" " * spaces + "~~~lang`info"), ("~", 3))
        self.assertIsNone(VALIDATOR._fence_start("```lang`info"))
        self.assertIsNone(VALIDATOR._fence_start("    ```text"))

        closed = VALIDATOR._source_flags(" ```text\n## Contract\n   ```\n## Contract\n")
        self.assertEqual(closed, [False, False, False, True])
        tilde_closed = VALIDATOR._source_flags(" ~~~lang`info\n## Contract\n ~~~~\n## Contract\n")
        self.assertEqual(tilde_closed, [False, False, False, True])
        unclosed = VALIDATOR._source_flags("   ```text\n## Contract\n## References\n")
        self.assertEqual(unclosed, [False, False, False])
        self.assertTrue(VALIDATOR._fence_close("  ``` \t", ("`", 3)))
        for suffix in ("\u00a0", "\v", "\f", "\r"):
            self.assertFalse(VALIDATOR._fence_close("```" + suffix, ("`", 3)))
        self.assertEqual(VALIDATOR._source_dialect_violations("model-routing.md", self.routing), [])

    def test_indented_and_tilde_unclosed_fences_fail_closed_before_contracts(self) -> None:
        for spaces in (1, 2, 3):
            opener = " " * spaces + "```text\n"
            before_contract = self.skill.replace("## Contract\n", opener + "## Contract\n", 1)
            self.assert_semantic_rejects(before_contract)
            self.assert_topology_rejects(before_contract)

            before_references = self.skill.replace("## References\n", opener + "## References\n", 1)
            self.assert_semantic_rejects(before_references)
            self.assert_topology_rejects(before_references)

        routing = self.routing.replace(
            "## Canonical routing contract\n",
            " ~~~lang`info\n## Canonical routing contract\n",
            1,
        )
        references = dict(self.references)
        references["model-routing.md"] = routing
        self.assert_semantic_rejects(self.skill, references)
        self.assert_topology_rejects(self.skill, references)

    def test_nbsp_is_not_a_fence_close_for_skill_and_routing(self) -> None:
        false_close = "```\u00a0\n"
        for section in ("## Contract\n", "## References\n"):
            candidate = self.skill.replace(section, "```text\n" + section + false_close, 1)
            self.assert_semantic_rejects(candidate)
            self.assert_topology_rejects(candidate)

        routing = self.routing.replace(
            "## Canonical routing contract\n",
            "```text\n## Canonical routing contract\n" + false_close,
            1,
        )
        references = dict(self.references)
        references["model-routing.md"] = routing
        self.assert_semantic_rejects(self.skill, references)
        self.assert_topology_rejects(self.skill, references)

    def test_task_contract_h1_and_h2_wrong_order_are_not_sentinels(self) -> None:
        wrong = self.task.replace("## 2. Ownership\n", "## 3. Inputs/evidence\n", 1)
        self.assertTrue(VALIDATOR.task_contract_violations(wrong))
        wrong = self.task.replace("## 5. Verification/handoff", "## 4. Constraints/requirements", 1)
        self.assertTrue(VALIDATOR.task_contract_violations(wrong))
        h1 = "# Subagent task contract\n"
        moved_after = self.task.replace(h1, "", 1) + "\n" + h1
        moved_between = self.task.replace(h1, "", 1).replace("## 3. Inputs/evidence\n", h1 + "## 3. Inputs/evidence\n", 1)
        self.assertTrue(VALIDATOR.task_contract_violations(moved_after))
        self.assertTrue(VALIDATOR.task_contract_violations(moved_between))

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
