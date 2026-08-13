#!/usr/bin/env python3
"""Focused offline tests for the registered versatile-dev source contract."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = ROOT / "payload/skills/versatile-dev/SKILL.md"
UI_PATH = ROOT / "payload/skills/versatile-dev/agents/openai.yaml"
REFERENCE_DIR = ROOT / "payload/skills/versatile-dev/references"
AGENT_DIR = ROOT / "payload/agents/common"
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

    def assert_semantic_diagnostic(
        self,
        candidate: str,
        diagnostic: str,
        references: dict[str, str] | None = None,
    ) -> None:
        self.assertNotEqual(candidate, self.skill, "mutation was a no-op")
        errors = VALIDATOR.semantic_contract_violations(
            candidate, references or self.references, self.ui
        )
        self.assertTrue(
            any(diagnostic in error for error in errors),
            f"missing diagnostic {diagnostic!r}: {errors}",
        )

    def validate_materialized(self, mutations: dict[str, bytes] | None = None) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for source in (SKILL_PATH, UI_PATH, *REFERENCE_DIR.glob("*.md")):
                target = root / source.relative_to(ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
            for relative, contents in (mutations or {}).items():
                (root / relative).write_bytes(contents)
            check = VALIDATOR.Validation()
            VALIDATOR.validate_skill(root, check)
            return check.errors

    def agent_errors(self, filename: str, sentence: str, section: str = "ALLOWED ACTIONS AND TOOLS") -> list[str]:
        path = AGENT_DIR / filename
        source = path.read_text(encoding="utf-8")
        marker = f"# {section}\n"
        candidate = source.replace(marker, marker + sentence + "\n", 1)
        self.assertNotEqual(candidate, source, "agent mutation was a no-op")
        data = tomllib.loads(candidate)
        return VALIDATOR.agent_contract_violations(data, str(path))

    def test_real_tree_is_valid(self) -> None:
        self.assertEqual(VALIDATOR.semantic_contract_violations(self.skill, self.references, self.ui), [])
        self.assertEqual(VALIDATOR.reference_topology_violations(self.skill, self.references, SKILL_PATH), [])
        self.assertEqual(VALIDATOR.task_contract_violations(self.task), [])
        self.assertEqual(self.validate_materialized(), [])

    def test_validate_skill_preserves_newlines_and_rejects_invalid_utf8(self) -> None:
        sources = (
            ("payload/skills/versatile-dev/SKILL.md", SKILL_PATH.read_bytes()),
            ("payload/skills/versatile-dev/references/workflow.md", (REFERENCE_DIR / "workflow.md").read_bytes()),
            ("payload/skills/versatile-dev/agents/openai.yaml", UI_PATH.read_bytes()),
        )
        for relative, contents in sources:
            for newline in (b"\r\n", b"\r"):
                errors = self.validate_materialized({relative: contents.replace(b"\n", newline)})
                self.assertTrue(errors, f"{relative} accepted {newline!r}")
        errors = self.validate_materialized({"payload/skills/versatile-dev/SKILL.md": b"\xff\n"})
        self.assertTrue(any("invalid UTF-8 controlled source" in error for error in errors))

    def test_split_raw_html_wrappers_fail_closed_in_memory_and_on_disk(self) -> None:
        begin, end, _ = VALIDATOR.CANONICAL_BLOCKS["SKILL.md"]
        split_open = '<div\nclass="masked">\n'
        split_close = '\n</div\n>\n'
        wrapped_block = self.skill.replace(begin, split_open + begin, 1).replace(end, end + split_close, 1)
        self.assert_semantic_rejects(wrapped_block)
        self.assert_topology_rejects(wrapped_block)

        sources = list(VALIDATOR.DIRECT_LINK_LINES.values())
        wrapped_links = self.skill.replace(sources[0], split_open + sources[0], 1).replace(
            sources[-1], sources[-1] + split_close, 1
        )
        self.assert_semantic_rejects(wrapped_links)
        self.assert_topology_rejects(wrapped_links)

        routing_begin, routing_end, _ = VALIDATOR.CANONICAL_BLOCKS["model-routing.md"]
        wrapped_routing = self.routing.replace(
            routing_begin, split_open + routing_begin, 1
        ).replace(routing_end, routing_end + split_close, 1)
        references = dict(self.references)
        references["model-routing.md"] = wrapped_routing
        self.assert_semantic_rejects(self.skill, references)
        self.assert_topology_rejects(self.skill, references)

        mutations = {
            "payload/skills/versatile-dev/SKILL.md": wrapped_block.encode("utf-8"),
            "payload/skills/versatile-dev/references/model-routing.md": wrapped_routing.encode("utf-8"),
        }
        errors = self.validate_materialized(mutations)
        self.assertTrue(any(error.startswith("SKILL.md:") and "unsupported angle or HTML" in error for error in errors))
        self.assertTrue(any(error.startswith("model-routing.md:") and "unsupported angle or HTML" in error for error in errors))

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
        self.assert_semantic_rejects(fenced_peer)
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
        self.assert_semantic_rejects(fenced_empty)
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

    def test_canonical_block_requires_exact_section_adjacency(self) -> None:
        self.assertEqual(VALIDATOR.canonical_block_violations("SKILL.md", self.skill), [])
        self.assertEqual(VALIDATOR.canonical_block_violations("model-routing.md", self.routing), [])
        mutations = (
            " ## Peer\n",
            "   # Peer\n",
            "Injected peer\n---\n",
            "Inserted prose\n",
            "\n",
        )
        for insertion in mutations:
            skill_candidate = self.skill.replace(
                "## Contract\n\n",
                "## Contract\n" + insertion + "\n",
                1,
            )
            self.assert_semantic_rejects(skill_candidate)
            self.assert_topology_rejects(skill_candidate)

            routing_candidate = self.routing.replace(
                "## Canonical routing contract\n\n",
                "## Canonical routing contract\n" + insertion + "\n",
                1,
            )
            references = dict(self.references)
            references["model-routing.md"] = routing_candidate
            self.assert_semantic_rejects(self.skill, references)
            self.assert_topology_rejects(self.skill, references)

        for text, filename, section in (
            (self.skill, "SKILL.md", "## Contract"),
            (self.routing, "model-routing.md", "## Canonical routing contract"),
        ):
            begin = VALIDATOR.CANONICAL_BLOCKS[filename][0]
            no_blank = text.replace(section + "\n\n" + begin, section + "\n" + begin, 1)
            if filename == "SKILL.md":
                self.assert_semantic_rejects(no_blank)
                self.assert_topology_rejects(no_blank)
            else:
                references = dict(self.references)
                references[filename] = no_blank
                self.assert_semantic_rejects(self.skill, references)
                self.assert_topology_rejects(self.skill, references)

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

    def test_direct_reference_topology_requires_active_inline_usages(self) -> None:
        definitions = "\n".join(
            f"[definition-{i}]: {target}"
            for i, target in enumerate(VALIDATOR.DIRECT_LINK_LINES)
        )
        removed = self.skill
        for source in VALIDATOR.DIRECT_LINK_LINES.values():
            removed = removed.replace(source, "", 1)
        cases = (
            ("definition-only", removed + "\n" + definitions),
            (
                "unused-definition-with-all-inline-links",
                self.skill + "\n[unused]: references/model-routing.md\n",
            ),
            (
                "masked-definition-only",
                removed + "\n```text\n[masked]: references/model-routing.md\n```\n",
            ),
            (
                "masked-inline-only",
                removed
                + "\n```text\n[model routing](references/model-routing.md)\n```\n",
            ),
        )
        for name, candidate in cases:
            with self.subTest(mutation=name):
                self.assertNotEqual(candidate, self.skill)
                errors = VALIDATOR.reference_topology_violations(
                    candidate, self.references, SKILL_PATH
                )
                if "definition" in name:
                    self.assertTrue(
                        any("definition cannot satisfy" in error for error in errors),
                        errors,
                    )
                else:
                    self.assertTrue(
                        any("exactly one active direct link" in error for error in errors),
                        errors,
                    )
        self.assertEqual(
            VALIDATOR.reference_topology_violations(
                self.skill, self.references, SKILL_PATH
            ),
            [],
        )

    def test_registered_app_and_failure_polarity_is_closed_and_line_local(self) -> None:
        rejecting = (
            (
                "app could",
                "App tasks could be created without explicit authorization.",
                "App task creation without explicit authorization",
            ),
            (
                "app can",
                "App tasks can be created without explicit authorization.",
                "App task creation without explicit authorization",
            ),
            (
                "app may with whitespace",
                "APP   TASKS   MAY   BE   CREATED, WITHOUT EXPLICIT AUTHORIZATION!",
                "App task creation without explicit authorization",
            ),
            (
                "app allowed",
                "App tasks are allowed to be created without explicit authorization.",
                "App task creation without explicit authorization",
            ),
            (
                "app creation allowed",
                "App task creation is allowed without explicit authorization.",
                "App task creation without explicit authorization",
            ),
            (
                "app authorizes",
                "App task creation authorizes without explicit authorization.",
                "App task creation without explicit authorization",
            ),
            (
                "failure could",
                "Content failures could authorize Terra fallback.",
                "failure authorization of Terra fallback",
            ),
            (
                "failure allowed",
                "Content failures are allowed to authorize Terra fallback.",
                "failure authorization of Terra fallback",
            ),
            (
                "failure may route switch",
                "Content, task, or tool failure may authorize route switching.",
                "failure authorization of Terra fallback",
            ),
            (
                "failure authorizes",
                "Content failures authorizes Terra fallback.",
                "failure authorization of Terra fallback",
            ),
            (
                "legal-then-app",
                "Do not create an App task without explicit authorization, and App tasks could be created without explicit authorization.",
                "App task creation without explicit authorization",
            ),
            (
                "legal-then-failure",
                "Content failures do not authorize Terra fallback, and Content failures could authorize Terra fallback.",
                "failure authorization of Terra fallback",
            ),
        )
        for name, sentence, diagnostic in rejecting:
            with self.subTest(mutation=name):
                self.assert_semantic_diagnostic(
                    self.skill + "\n" + sentence + "\n", diagnostic
                )

        accepted = (
            "Do not create an App task without explicit authorization.",
            "App tasks cannot be created without explicit authorization.",
            "App tasks are not allowed to be created without explicit authorization.",
            "Content failures do not authorize Terra fallback.",
            "Content failures could not authorize Terra fallback.",
            "Do not say: App tasks could be created without explicit authorization.",
            "App tasks could be\ncreated without explicit authorization.",
            "App tasks could be\n\ncreated without explicit authorization.",
            "```text\nApp tasks could be created without explicit authorization.\n```",
        )
        for sentence in accepted:
            with self.subTest(control=sentence):
                candidate = self.skill + "\n" + sentence + "\n"
                self.assertNotEqual(candidate, self.skill)
                self.assertEqual(
                    VALIDATOR.semantic_contract_violations(
                        candidate, self.references, self.ui
                    ),
                    [],
                )

    def test_polarity_punctuation_and_modal_families_cover_skill_and_agent_paths(self) -> None:
        app_diagnostic = "App task creation without explicit authorization"
        failure_diagnostic = "failure authorization of Terra fallback"
        cases = (
            ("app-may", "App tasks may be created without explicit authorization.", app_diagnostic),
            ("app-can", "App tasks can be created without explicit authorization.", app_diagnostic),
            ("app-could-semicolon", "App tasks could; be created without explicit authorization.", app_diagnostic),
            ("app-are-allowed", "App tasks are allowed to be created without explicit authorization.", app_diagnostic),
            ("app-is-allowed-colon", "App task creation is allowed: without explicit authorization.", app_diagnostic),
            ("app-be-allowed-dash", "App tasks be allowed to be created — without explicit authorization.", app_diagnostic),
            ("app-direct-action", "App task creation authorizes, without explicit authorization.", app_diagnostic),
            ("failure-may", "Content failures may authorize Terra fallback.", failure_diagnostic),
            ("failure-can-colon", "Content failures can authorize: Terra fallback.", failure_diagnostic),
            ("failure-could-semicolon", "Content failures could authorize; Terra fallback.", failure_diagnostic),
            ("failure-are-allowed", "Content failures are allowed to authorize Terra fallback.", failure_diagnostic),
            ("failure-direct-action-dash", "Content failures authorizes — Terra fallback.", failure_diagnostic),
            ("case-and-space", "APP   TASKS   MAY   BE   CREATED, WITHOUT EXPLICIT AUTHORIZATION!", app_diagnostic),
        )
        for name, sentence, diagnostic in cases:
            with self.subTest(path="Skill", mutation=name):
                self.assert_semantic_diagnostic(self.skill + "\n" + sentence + "\n", diagnostic)

            filename = "architect.toml" if diagnostic == app_diagnostic else "docs_researcher_luna.toml"
            with self.subTest(path="agent", mutation=name):
                errors = self.agent_errors(filename, sentence)
                self.assertTrue(
                    any(diagnostic in error for error in errors),
                    f"missing diagnostic {diagnostic!r}: {errors}",
                )

    def test_ascii_hyphen_suffixes_are_checked_on_skill_and_agent_paths(self) -> None:
        cases = (
            (
                "app-legal-then-contradiction",
                "App tasks cannot be created without authorization - App tasks could be created without authorization.",
                "App task creation without explicit authorization",
                "architect.toml",
            ),
            (
                "failure-legal-then-contradiction",
                "Content failures do not authorize Terra fallback - Content failures could authorize Terra fallback.",
                "failure authorization of Terra fallback",
                "docs_researcher_luna.toml",
            ),
        )
        for name, sentence, diagnostic, filename in cases:
            with self.subTest(path="Skill", mutation=name):
                self.assert_semantic_diagnostic(self.skill + "\n" + sentence + "\n", diagnostic)
            with self.subTest(path="agent", mutation=name):
                errors = self.agent_errors(filename, sentence)
                self.assertTrue(any(diagnostic in error for error in errors), errors)

    def test_ascii_hyphen_boundary_stays_out_of_tokens_and_hard_boundaries(self) -> None:
        skill_controls = (
            "Quoted-App tasks could be created without authorization.",
            "well-known prose about App tasks could be created without authorization.",
            "-",
            "- ordinary list marker",
            "App tasks could\nbe created without authorization.",
            "- App tasks could\n- be created without authorization.",
            "App tasks could\n\nbe created without authorization.",
            "```text\nApp tasks could - be created without authorization.\n```",
        )
        for sentence in skill_controls:
            with self.subTest(path="Skill", control=sentence):
                candidate = self.skill + "\n" + sentence + "\n"
                self.assertNotEqual(candidate, self.skill, "mutation was a no-op")
                self.assertEqual(
                    VALIDATOR.semantic_contract_violations(candidate, self.references, self.ui),
                    [],
                )

        agent_controls = (
            "Quoted-App tasks could be created without authorization.",
            "well-known prose about App tasks could be created without authorization.",
            "-",
            "- ordinary list marker",
            "App tasks could\nbe created without authorization.",
            "- App tasks could\n- be created without authorization.",
            "App tasks could\n\nbe created without authorization.",
        )
        for sentence in agent_controls:
            with self.subTest(path="agent", control=sentence):
                self.assertEqual(self.agent_errors("architect.toml", sentence), [])

        references = dict(self.references)
        references["workflow.md"] += "\n```text\nContent failures could authorize - Terra fallback.\n```\n"
        self.assertEqual(
            VALIDATOR.semantic_contract_violations(self.skill, references, self.ui),
            [],
        )

    def test_polarity_inline_code_projection_is_bounded_and_shared(self) -> None:
        app_diagnostic = "App task creation without explicit authorization"
        failure_diagnostic = "failure authorization of Terra fallback"
        rejecting = (
            (
                "app-after-inline-code",
                "App tasks could be created without authorization. `benign`",
                app_diagnostic,
                "architect.toml",
            ),
            (
                "app-before-inline-code",
                "`benign` App tasks could be created without authorization.",
                app_diagnostic,
                "architect.toml",
            ),
            (
                "app-between-inline-code",
                "App tasks could be `benign` created without authorization.",
                app_diagnostic,
                "architect.toml",
            ),
            (
                "failure-after-inline-code",
                "Content failures could authorize Terra fallback. `benign`",
                failure_diagnostic,
                "docs_researcher_luna.toml",
            ),
            (
                "failure-before-inline-code",
                "`benign` Content failures could authorize Terra fallback.",
                failure_diagnostic,
                "docs_researcher_luna.toml",
            ),
            (
                "failure-between-inline-code",
                "Content failures could `benign` authorize Terra fallback.",
                failure_diagnostic,
                "docs_researcher_luna.toml",
            ),
            (
                "app-multiple-inline-spans",
                "App tasks could be created without authorization. `one` and `two`",
                app_diagnostic,
                "architect.toml",
            ),
            (
                "app-escaped-backticks-are-active",
                r"App tasks could be created without authorization. \`benign\`",
                app_diagnostic,
                "architect.toml",
            ),
            (
                "failure-escaped-backticks-are-active",
                r"Content failures could authorize Terra fallback. \`benign\`",
                failure_diagnostic,
                "docs_researcher_luna.toml",
            ),
        )
        for name, sentence, diagnostic, filename in rejecting:
            with self.subTest(path="Skill", mutation=name):
                self.assert_semantic_diagnostic(self.skill + "\n" + sentence + "\n", diagnostic)
            with self.subTest(path="agent", mutation=name):
                agent_sentence = sentence.replace("\\", "\\\\")
                errors = self.agent_errors(filename, agent_sentence)
                self.assertTrue(any(diagnostic in error for error in errors), errors)

        accepted = (
            (
                "app-inline-code-only",
                "`App tasks could be created without authorization.`",
                "architect.toml",
            ),
            (
                "failure-inline-code-only",
                "`Content failures could authorize Terra fallback.`",
                "docs_researcher_luna.toml",
            ),
            (
                "app-unsafe-inside-code-with-benign-prose",
                "`App tasks could be created without authorization.` note",
                "architect.toml",
            ),
            (
                "failure-unsafe-inside-code-with-benign-prose",
                "`Content failures could authorize Terra fallback.` note",
                "docs_researcher_luna.toml",
            ),
            (
                "app-fully-fenced",
                "```text\nApp tasks could be created without authorization.\n```",
                "architect.toml",
            ),
            (
                "failure-fully-fenced",
                "~~~text\nContent failures could authorize Terra fallback.\n~~~",
                "docs_researcher_luna.toml",
            ),
            (
                "app-unmatched-run-is-inactive",
                "App tasks could be created without authorization. `unmatched",
                "architect.toml",
            ),
            (
                "failure-mismatched-runs-are-inactive",
                "Content failures could authorize Terra fallback. `one ``two",
                "docs_researcher_luna.toml",
            ),
        )
        for name, sentence, filename in accepted:
            with self.subTest(path="Skill", control=name):
                candidate = self.skill + "\n" + sentence + "\n"
                self.assertNotEqual(candidate, self.skill, "mutation was a no-op")
                self.assertEqual(
                    VALIDATOR.semantic_contract_violations(candidate, self.references, self.ui),
                    [],
                )
            with self.subTest(path="agent", control=name):
                self.assertEqual(self.agent_errors(filename, sentence), [])

    def test_polarity_keeps_hard_boundaries_and_negation_local(self) -> None:
        app_diagnostic = "App task creation without explicit authorization"
        failure_diagnostic = "failure authorization of Terra fallback"
        controls = (
            "App tasks could,\nbe created without explicit authorization.",
            "App tasks could\nbe created without explicit authorization.",
            "App tasks could\n\nbe created without explicit authorization.",
            "- App tasks could\n- be created without explicit authorization.",
            "Content failures could authorize,\nTerra fallback.",
        )
        for sentence in controls:
            with self.subTest(path="Skill", control=sentence):
                candidate = self.skill + "\n" + sentence + "\n"
                self.assertNotEqual(candidate, self.skill)
                self.assertEqual(
                    VALIDATOR.semantic_contract_violations(candidate, self.references, self.ui),
                    [],
                )
            with self.subTest(path="agent", control=sentence):
                self.assertEqual(self.agent_errors("architect.toml", sentence), [])

        section_split = self.skill + "\nApp tasks could\n"
        split_references = dict(self.references)
        split_references["workflow.md"] += "\nbe created without explicit authorization.\n"
        self.assertEqual(
            VALIDATOR.semantic_contract_violations(section_split, split_references, self.ui),
            [],
        )

        agent_path = AGENT_DIR / "architect.toml"
        source = agent_path.read_text(encoding="utf-8")
        split_candidate = source.replace(
            "# OWNERSHIP\n", "# OWNERSHIP\nApp tasks could\n", 1
        ).replace(
            "# ALLOWED ACTIONS AND TOOLS\n",
            "# ALLOWED ACTIONS AND TOOLS\nbe created without explicit authorization.\n",
            1,
        )
        self.assertNotEqual(split_candidate, source)
        self.assertEqual(
            VALIDATOR.agent_contract_violations(tomllib.loads(split_candidate), str(agent_path)),
            [],
        )

        rejecting = (
            "Do not create an App task without explicit authorization, and App tasks could; be created without explicit authorization.",
            "Content failures do not authorize Terra fallback; Content failures could authorize; Terra fallback.",
        )
        for sentence in rejecting:
            diagnostic = app_diagnostic if sentence.startswith("Do not create") else failure_diagnostic
            with self.subTest(path="Skill", mutation=sentence):
                self.assert_semantic_diagnostic(self.skill + "\n" + sentence + "\n", diagnostic)
            filename = "architect.toml" if diagnostic == app_diagnostic else "docs_researcher_luna.toml"
            with self.subTest(path="agent", mutation=sentence):
                errors = self.agent_errors(filename, sentence)
                self.assertTrue(any(diagnostic in error for error in errors), errors)

    def test_quoted_quote_and_example_protect_only_the_immediate_clause(self) -> None:
        app_diagnostic = "App task creation without explicit authorization"
        failure_diagnostic = "failure authorization of Terra fallback"
        app_sentence = "App tasks could be created without explicit authorization."
        failure_sentence = "Content failures could authorize Terra fallback."
        benign = (
            ("quoted-colon-app", "Quoted: " + app_sentence, "architect.toml"),
            ("quote-fullwidth-failure", "Quote： " + failure_sentence, "docs_researcher_luna.toml"),
            ("example-colon-app", "Example: " + app_sentence, "architect.toml"),
            ("example-fullwidth-failure", "Example： " + failure_sentence, "docs_researcher_luna.toml"),
        )
        for name, sentence, filename in benign:
            with self.subTest(path="Skill", mutation=name):
                candidate = self.skill + "\n" + sentence + "\n"
                self.assertNotEqual(candidate, self.skill)
                self.assertEqual(
                    VALIDATOR.semantic_contract_violations(candidate, self.references, self.ui),
                    [],
                )
            with self.subTest(path="agent", mutation=name):
                self.assertEqual(self.agent_errors(filename, sentence), [])

        rejecting = (
            (
                "quoted-later-app",
                "Quoted: " + app_sentence[:-1] + ", and " + app_sentence,
                app_diagnostic,
                "architect.toml",
            ),
            (
                "example-later-failure",
                "Example: " + failure_sentence[:-1] + "; " + failure_sentence,
                failure_diagnostic,
                "docs_researcher_luna.toml",
            ),
        )
        for name, sentence, diagnostic, filename in rejecting:
            with self.subTest(path="Skill", mutation=name):
                self.assert_semantic_diagnostic(self.skill + "\n" + sentence + "\n", diagnostic)
            with self.subTest(path="agent", mutation=name):
                errors = self.agent_errors(filename, sentence)
                self.assertTrue(any(diagnostic in error for error in errors), errors)

    def test_registered_quoting_introducers_protect_semicolon_immediate_clause(self) -> None:
        app_diagnostic = "App task creation without explicit authorization"
        failure_diagnostic = "failure authorization of Terra fallback"
        app_sentence = "App tasks could be created without explicit authorization."
        failure_sentence = "Content failures could authorize Terra fallback."
        benign = (
            ("quoted-semicolon-app", "Quoted; " + app_sentence, app_diagnostic, "architect.toml"),
            ("quote-semicolon-app", "Quote; " + app_sentence, app_diagnostic, "architect.toml"),
            ("example-semicolon-app", "Example; " + app_sentence, app_diagnostic, "architect.toml"),
            (
                "quoted-semicolon-failure",
                "Quoted; " + failure_sentence,
                failure_diagnostic,
                "docs_researcher_luna.toml",
            ),
            (
                "quote-semicolon-failure",
                "Quote; " + failure_sentence,
                failure_diagnostic,
                "docs_researcher_luna.toml",
            ),
            (
                "example-semicolon-failure",
                "Example; " + failure_sentence,
                failure_diagnostic,
                "docs_researcher_luna.toml",
            ),
        )
        for name, sentence, diagnostic, filename in benign:
            with self.subTest(path="Skill", control=name):
                candidate = self.skill + "\n" + sentence + "\n"
                self.assertNotEqual(candidate, self.skill, "mutation was a no-op")
                self.assertEqual(
                    VALIDATOR.semantic_contract_violations(candidate, self.references, self.ui),
                    [],
                )
            with self.subTest(path="agent", control=name):
                self.assertEqual(self.agent_errors(filename, sentence), [])

        rejecting = (
            (
                "quoted-later-semicolon-app",
                "Quoted; " + app_sentence[:-1] + "; " + app_sentence,
                app_diagnostic,
                "architect.toml",
            ),
            (
                "quote-later-conjunction-app",
                "Quote; " + app_sentence[:-1] + ", and " + app_sentence,
                app_diagnostic,
                "architect.toml",
            ),
            (
                "example-later-semicolon-app",
                "Example; " + app_sentence[:-1] + "; " + app_sentence,
                app_diagnostic,
                "architect.toml",
            ),
            (
                "quoted-later-conjunction-failure",
                "Quoted; " + failure_sentence[:-1] + ", and " + failure_sentence,
                failure_diagnostic,
                "docs_researcher_luna.toml",
            ),
            (
                "quote-later-semicolon-failure",
                "Quote; " + failure_sentence[:-1] + "; " + failure_sentence,
                failure_diagnostic,
                "docs_researcher_luna.toml",
            ),
            (
                "example-later-conjunction-failure",
                "Example; " + failure_sentence[:-1] + ", and " + failure_sentence,
                failure_diagnostic,
                "docs_researcher_luna.toml",
            ),
        )
        for name, sentence, diagnostic, filename in rejecting:
            with self.subTest(path="Skill", mutation=name):
                self.assert_semantic_diagnostic(self.skill + "\n" + sentence + "\n", diagnostic)
            with self.subTest(path="agent", mutation=name):
                errors = self.agent_errors(filename, sentence)
                self.assertTrue(any(diagnostic in error for error in errors), errors)

    def test_fenced_h2_h3_lines_fail_closed_without_breaking_code_fences(self) -> None:
        mutations = (
            ("skill-canonical-backtick", "SKILL.md", "```text\n## Contract\n```"),
            ("skill-peer-tilde", "SKILL.md", "  ~~~~\n   ### Peer\n  ~~~~"),
            (
                "routing-canonical-long-backtick",
                "model-routing.md",
                "````text\n  ## Canonical routing contract\n````",
            ),
            (
                "workflow-peer-invalid-close",
                "workflow.md",
                "~~~\n### Peer\n~~~suffix\n",
            ),
            (
                "reference-peer",
                "review-policy.md",
                "```\n## Unrelated peer\n```",
            ),
        )
        for name, filename, fence in mutations:
            with self.subTest(mutation=name):
                if filename == "SKILL.md":
                    candidate = self.skill + "\n" + fence + "\n"
                    errors = VALIDATOR.semantic_contract_violations(
                        candidate, self.references, self.ui
                    )
                else:
                    references = dict(self.references)
                    references[filename] += "\n" + fence + "\n"
                    candidate = self.skill
                    errors = VALIDATOR.semantic_contract_violations(
                        candidate, references, self.ui
                    )
                if filename == "SKILL.md":
                    self.assertNotEqual(candidate, self.skill)
                else:
                    self.assertNotEqual(references[filename], self.references[filename])
                self.assertTrue(
                    any("unsupported H2/H3 heading inside a fenced source block" in error for error in errors),
                    errors,
                )

        ordinary = dict(self.references)
        ordinary["workflow.md"] += "\n```text\nordinary code\n```\n"
        self.assertEqual(
            VALIDATOR.semantic_contract_violations(self.skill, ordinary, self.ui),
            [],
        )

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

    def test_lf_only_source_lines_reject_all_unsupported_separators(self) -> None:
        self.assertEqual(VALIDATOR._source_lines("one\r\ntwo"), ["one\r", "two"])
        separators = ("\r", "\v", "\f", "\x85", "\u2028", "\u2029")
        for separator in separators:
            self.assertFalse(VALIDATOR._fence_close("```" + separator, ("`", 3)))
            self.assertTrue(VALIDATOR._source_separator_violations("probe.md", "plain" + separator + "text"))

            false_close = "```" + separator + "\n"
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

            non_fence = dict(self.references)
            non_fence["workflow.md"] += "\nplain" + separator + "text\n"
            self.assert_semantic_rejects(self.skill, non_fence)
            self.assert_topology_rejects(self.skill, non_fence)

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
