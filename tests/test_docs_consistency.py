#!/usr/bin/env python3
"""Durable offline checks for the public documentation facts."""

from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
DEVELOPMENT_PLAN = ROOT / "DEVELOPMENT_PLAN.md"
AGENT_ROOT = ROOT / "payload/agents/common"
RUN_SCRIPT = ROOT / "tests/run.sh"
PACKAGE_SCRIPT = ROOT / "package.sh"

EXPECTED_AGENTS = {
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


class DocumentationConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.readme = README.read_text(encoding="utf-8")
        cls.plan = DEVELOPMENT_PLAN.read_text(encoding="utf-8")
        cls.docs = f"{cls.readme}\n{cls.plan}"

    def test_source_has_thirteen_unique_agents_and_two_named_researchers(self) -> None:
        paths = sorted(AGENT_ROOT.glob("*.toml"))
        self.assertEqual(len(paths), 13)
        self.assertEqual({path.stem for path in paths}, EXPECTED_AGENTS)
        self.assertNotIn("docs_researcher.toml", {path.name for path in paths})

        documents = [tomllib.loads(path.read_text(encoding="utf-8")) for path in paths]
        names = [document["name"] for document in documents]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), EXPECTED_AGENTS)
        for name in EXPECTED_AGENTS:
            self.assertIn(name, self.docs)
        for name, model, effort in (
            ("docs_researcher_luna", "gpt-5.6-luna", "max"),
            ("docs_researcher_terra", "gpt-5.6-terra", "high"),
        ):
            document = next(item for item in documents if item["name"] == name)
            self.assertEqual(document["model"], model)
            self.assertEqual(document["model_reasoning_effort"], effort)

    def test_docs_state_current_dual_route_and_evidence_boundaries(self) -> None:
        for phrase in (
            "13 unique",
            "docs_researcher_luna",
            "docs_researcher_terra",
            "same canonical `task_packet_hash`",
            "STOP_FAILED",
            "STOP_UNVERIFIED",
            "selected_profile",
            "runtime_audit.py",
            "requested_*",
            "configured_*",
            "observed_effective_*",
            "explicit authorization in the current",
            "gpt-5.6-luna` / `max`",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.docs)

    def test_stale_single_profile_and_future_claims_are_absent(self) -> None:
        forbidden = (
            "twelve narrow custom agents",
            "12 narrow custom agents",
            "12 agents",
            "current installer selects one legacy `docs_researcher` profile",
            "future work",
            "selects Terra/High fallback",
            "Luna unavailable",
        )
        for phrase in forbidden:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase.casefold(), self.docs.casefold())

    def test_live_boundary_and_offline_gate_are_explicit(self) -> None:
        for phrase in (
            "tests/test_live_codex.sh",
            "schema-review harness only",
            "no authentication",
            "fresh Codex task",
            "always returns `UNVERIFIED`",
            "cannot establish live runtime fallback or conformance",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.docs)

        run_script = RUN_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("test_docs_consistency.py", run_script)
        self.assertNotIn("test_live_codex.sh", run_script)
        self.assertNotIn("RUN_CODEX_LIVE", run_script)

    def test_documented_package_commands_and_staged_files_match_script(self) -> None:
        for command in ("./validate.sh", "./tests/run.sh", "./package.sh"):
            with self.subTest(command=command):
                self.assertIn(command, self.readme)

        package = PACKAGE_SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("test_live_codex.sh", package)
        self.assertNotIn("RUN_CODEX_LIVE", package)
        for staged_path in (
            '"$bundle_root/README.md"',
            '"$bundle_root/DEVELOPMENT_PLAN.md"',
            '"$bundle_root/tests"',
        ):
            with self.subTest(staged_path=staged_path):
                self.assertIn(staged_path, package)
        self.assertIn("SHA256SUMS", self.readme)
        self.assertRegex(self.docs, re.compile(r"codex-versatile-agent-workflow-<version>\.tar\.gz"))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
