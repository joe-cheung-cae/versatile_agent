#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


sys.dont_write_bytecode = True


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("merge_config", ROOT / "scripts/merge_config.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

DIVERGENT_AGENTS = """[agents]
enabled = false
max_concurrent_threads_per_session = 2
default_subagent_model = "gpt-5.6-sol"
default_subagent_reasoning_effort = "low"
interrupt_message = false
"""


class MergeConfigTests(unittest.TestCase):
    def test_appends_agents_section(self) -> None:
        merged = MODULE.merge_text('model = "gpt-5.6-sol"\n')
        self.assertIn('[agents]\n', merged)
        self.assertIn('default_subagent_model = "gpt-5.6-terra"\n', merged)
        self.assertTrue(merged.startswith('model = "gpt-5.6-sol"\n'))

    def test_updates_only_managed_keys(self) -> None:
        original = """model = "keep-me"

[agents]
max_concurrent_threads_per_session = 2
custom_key = "preserve"

[features]
example = true
"""
        merged = MODULE.merge_text(original)
        self.assertIn('model = "keep-me"', merged)
        self.assertIn('custom_key = "preserve"', merged)
        self.assertIn('[features]\nexample = true', merged)
        self.assertIn('max_concurrent_threads_per_session = 2', merged)
        self.assertNotIn('max_concurrent_threads_per_session = 6', merged)
        self.assertIn('enabled = true', merged)
        self.assertIn('default_subagent_model = "gpt-5.6-terra"', merged)
        self.assertEqual(merged.count('[agents]'), 1)

    def test_force_replaces_present_managed_keys(self) -> None:
        original = """model = "keep-me"

[agents]
max_concurrent_threads_per_session = 2
custom_key = "preserve"

[features]
example = true
"""
        merged = MODULE.merge_text(original, force=True)
        self.assertIn('model = "keep-me"', merged)
        self.assertIn('custom_key = "preserve"', merged)
        self.assertIn('[features]\nexample = true', merged)
        self.assertIn('max_concurrent_threads_per_session = 6', merged)
        self.assertNotIn('max_concurrent_threads_per_session = 2', merged)
        self.assertEqual(merged.count('[agents]'), 1)

    def test_is_idempotent(self) -> None:
        first = MODULE.merge_text("")
        second = MODULE.merge_text(first)
        self.assertEqual(first, second)
        self.assertEqual(first, MODULE.merge_text(first, force=True))

    def test_rejects_invalid_toml(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.merge_text("[agents\n")

    def test_rejects_duplicate_agents_sections(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.merge_text("[agents]\nenabled=true\n[agents]\nenabled=false\n")

    def test_stops_before_array_table(self) -> None:
        original = """[agents]
custom_key = "preserve"

[[hooks]]
name = "example"
"""
        merged = MODULE.merge_text(original)
        agents_text, hooks_text = merged.split("[[hooks]]", 1)
        self.assertIn('default_subagent_model = "gpt-5.6-terra"', agents_text)
        self.assertNotIn("default_subagent_model", hooks_text)
        self.assertIn('name = "example"', hooks_text)

    def test_check_accepts_divergent_values_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(DIVERGENT_AGENTS, encoding="utf-8")
            self.assertEqual(self._run_cli(path, "--check"), 0)
            self.assertEqual(path.read_text(encoding="utf-8"), DIVERGENT_AGENTS)

    def test_check_force_requires_hardcoded_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(DIVERGENT_AGENTS, encoding="utf-8")
            self.assertEqual(self._run_cli(path, "--check", "--force-config"), 1)
            self.assertEqual(path.read_text(encoding="utf-8"), DIVERGENT_AGENTS)
            path.write_text(MODULE.merge_text("", force=True), encoding="utf-8")
            self.assertEqual(self._run_cli(path, "--check", "--force-config"), 0)

    def test_check_fails_when_managed_keys_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("[agents]\nenabled = true\n", encoding="utf-8")
            self.assertEqual(self._run_cli(path, "--check"), 1)
            self.assertEqual(self._run_cli(path, "--check", "--force-config"), 1)

    def test_cli_force_replaces_present_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text(DIVERGENT_AGENTS, encoding="utf-8")
            self.assertEqual(self._run_cli(path), 0)
            self.assertIn("max_concurrent_threads_per_session = 2", path.read_text(encoding="utf-8"))
            self.assertEqual(self._run_cli(path, "--force-config"), 0)
            written = path.read_text(encoding="utf-8")
            self.assertIn("max_concurrent_threads_per_session = 6", written)
            self.assertIn('default_subagent_model = "gpt-5.6-terra"', written)

    def _run_cli(self, path: Path, *flags: str) -> int:
        previous = sys.argv
        sys.argv = ["merge_config.py", *flags, str(path)]
        try:
            return MODULE.main()
        finally:
            sys.argv = previous


if __name__ == "__main__":
    unittest.main()
