#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


sys.dont_write_bytecode = True


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("merge_config", ROOT / "scripts/merge_config.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


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
        self.assertIn('max_concurrent_threads_per_session = 6', merged)
        self.assertEqual(merged.count('[agents]'), 1)

    def test_is_idempotent(self) -> None:
        first = MODULE.merge_text("")
        second = MODULE.merge_text(first)
        self.assertEqual(first, second)

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


if __name__ == "__main__":
    unittest.main()
