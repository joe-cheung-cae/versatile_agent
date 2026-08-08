#!/usr/bin/env python3
"""Focused offline coverage for the P1-1 independent runtime-record contract."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


sys.dont_write_bytecode = True


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests/fixtures/runtime"
DETECTOR = ROOT / "payload/skills/versatile-dev/scripts/detect-runtime.sh"
HELPER = ROOT / "payload/skills/versatile-dev/scripts/runtime_records.py"
SPEC = importlib.util.spec_from_file_location("runtime_records", HELPER)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def read_fixture(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def without_capture(document: dict) -> dict:
    result = copy.deepcopy(document)
    for record in result.get("records", []):
        record["captured_at"] = "<captured-at>"
    return result


def run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HELPER), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def run_detector(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(DETECTOR), *args],
        check=False,
        capture_output=True,
        text=True,
    )


class RuntimeRecordTests(unittest.TestCase):
    def test_cli_and_app_records_have_complete_independent_contracts(self) -> None:
        document = read_fixture("cli-and-app-records.json")
        MODULE.validate_document(document)
        self.assertEqual({record["interface_kind"] for record in document["records"]}, {"cli_binary", "app_bundled_cli"})
        for record in document["records"]:
            self.assertTrue(set(MODULE.REQUIRED_FIELDS) <= set(record))
            self.assertTrue(record["diagnostic_only"])

    def test_runtime_ids_and_provenance_remain_distinct(self) -> None:
        document = read_fixture("cli-and-app-records.json")
        cli, app = document["records"]
        self.assertNotEqual(cli["runtime_id"], app["runtime_id"])
        self.assertNotEqual(cli["binary_path"], app["binary_path"])
        self.assertNotEqual(cli["version"], app["version"])
        self.assertNotEqual(cli["evidence_source"], app["evidence_source"])

        first_result = run_detector(
            "--format",
            "json",
            "--codex-bin",
            str(FIXTURE_ROOT / "cli-v1-luna.sh"),
            "--app-codex-bin",
            str(FIXTURE_ROOT / "app-v1-luna.sh"),
        )
        second_result = run_detector(
            "--format",
            "json",
            "--codex-bin",
            str(FIXTURE_ROOT / "cli-v1-luna.sh"),
            "--app-codex-bin",
            str(FIXTURE_ROOT / "app-luna-only.sh"),
        )
        self.assertEqual(first_result.returncode, 0, first_result.stderr)
        self.assertEqual(second_result.returncode, 0, second_result.stderr)
        first = json.loads(first_result.stdout)
        second = json.loads(second_result.stdout)
        self.assertNotEqual(
            {record["runtime_id"] for record in first["records"]},
            {record["runtime_id"] for record in second["records"]},
        )

    def test_model_and_effort_facts_stay_inside_their_record(self) -> None:
        document = read_fixture("cli-and-app-records.json")
        cli, app = document["records"]
        self.assertEqual(cli["model_support"], ["gpt-5.6-terra"])
        self.assertEqual(app["model_support"], ["gpt-5.6-luna"])
        self.assertEqual(app["effort_support"]["gpt-5.6-luna"], ["max"])
        result = MODULE.query_record(
            document,
            runtime_id=app["runtime_id"],
            require_models=["gpt-5.6-luna"],
            require_efforts=["gpt-5.6-luna:max"],
        )
        self.assertEqual(result["runtime_id"], app["runtime_id"])
        with self.assertRaises(MODULE.RuntimeRecordError):
            MODULE.query_record(
                document,
                runtime_id=cli["runtime_id"],
                require_models=["gpt-5.6-luna"],
            )

    def test_mixed_runtime_query_and_compatibility_recommendation_fail_closed(self) -> None:
        document = read_fixture("cli-and-app-records.json")
        recommendation = MODULE.recommend_profile(document["records"], "yes")
        self.assertEqual(recommendation[0], "terra-fallback")
        self.assertIn("fail closed", recommendation[2])
        with self.assertRaises(MODULE.RuntimeRecordError):
            MODULE.query_record(document, require_models=["gpt-5.6-luna"])

        detected = run_detector(
            "--format",
            "json",
            "--codex-bin",
            str(FIXTURE_ROOT / "cli-v2-no-luna.sh"),
            "--app-codex-bin",
            str(FIXTURE_ROOT / "app-luna-only.sh"),
            "--native-v2-luna",
            "yes",
        )
        self.assertEqual(detected.returncode, 0, detected.stderr)
        detected_document = json.loads(detected.stdout)
        self.assertNotIn("recommended_profile", detected_document)
        profile = run_detector(
            "--format",
            "profile",
            "--codex-bin",
            str(FIXTURE_ROOT / "cli-v2-no-luna.sh"),
            "--app-codex-bin",
            str(FIXTURE_ROOT / "app-luna-only.sh"),
            "--native-v2-luna",
            "yes",
        )
        self.assertEqual(profile.returncode, 0, profile.stderr)
        self.assertEqual(profile.stdout.strip(), "terra-fallback")

    def test_native_spawn_and_app_task_are_valid_only_as_separate_records(self) -> None:
        native = read_fixture("native-spawn.json")
        app_task = read_fixture("app-task.json")
        for document, interface_kind in ((native, "native_spawn_attempt"), (app_task, "app_task")):
            MODULE.validate_document(document)
            record = document["records"][0]
            self.assertEqual(record["interface_kind"], interface_kind)
            result = MODULE.query_record(
                document,
                runtime_id=record["runtime_id"],
                require_observed_model="gpt-5.6-luna",
                require_observed_effort="max",
            )
            self.assertEqual(result["runtime_id"], record["runtime_id"])
        self.assertFalse(any(key.startswith("effective_") for key in app_task["records"][0]["observed"]))
        combined = {"schema_version": 1, "records": native["records"] + app_task["records"]}
        with self.assertRaises(MODULE.RuntimeRecordError):
            MODULE.query_record(combined, require_observed_model="gpt-5.6-luna")

        detector = json.loads(
            run_detector(
                "--format",
                "json",
                "--codex-bin",
                str(FIXTURE_ROOT / "cli-v1-luna.sh"),
                "--app-codex-bin",
                str(FIXTURE_ROOT / "app-v1-luna.sh"),
            ).stdout
        )
        self.assertEqual(
            {record["interface_kind"] for record in detector["records"]},
            {"cli_binary", "app_bundled_cli"},
        )

    def test_invalid_and_unknown_fact_inputs_fail_nonzero(self) -> None:
        for fixture in (
            "missing-field.json",
            "duplicate-runtime-id.json",
            "mixed-evidence.json",
            "conflicting-observation.json",
        ):
            result = run_tool("validate", str(FIXTURE_ROOT / fixture))
            self.assertNotEqual(result.returncode, 0, fixture)
            self.assertIn("runtime-record error:", result.stderr, fixture)

        unknown = FIXTURE_ROOT / "unknown-fact.json"
        self.assertEqual(run_tool("validate", str(unknown)).returncode, 0)
        query = run_tool(
            "query",
            str(unknown),
            "--runtime-id",
            "fixture-unknown-facts",
            "--require-model",
            "gpt-5.6-luna",
            "--require-effort",
            "gpt-5.6-luna:max",
        )
        self.assertNotEqual(query.returncode, 0)
        self.assertIn("absent/unknown", query.stderr)

    def test_serialization_is_deterministic_and_ordered(self) -> None:
        document = read_fixture("cli-and-app-records.json")
        reversed_document = copy.deepcopy(document)
        reversed_document["records"].reverse()
        self.assertEqual(MODULE.canonical_json(document), MODULE.canonical_json(reversed_document))

        changed_capture = copy.deepcopy(document)
        changed_capture["records"][0]["captured_at"] = "2026-08-08T00:00:01Z"
        self.assertNotEqual(MODULE.canonical_json(document), MODULE.canonical_json(changed_capture))
        self.assertEqual(without_capture(document), without_capture(changed_capture))

        output = run_detector(
            "--format",
            "json",
            "--codex-bin",
            str(FIXTURE_ROOT / "cli-v1-luna.sh"),
            "--app-codex-bin",
            str(FIXTURE_ROOT / "app-v1-luna.sh"),
        )
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertLess(
            output.stdout.index('"interface_kind": "cli_binary"'),
            output.stdout.index('"interface_kind": "app_bundled_cli"'),
        )

    def test_env_and_profile_compatibility_are_diagnostic_and_single_record(self) -> None:
        env = run_detector(
            "--format",
            "env",
            "--codex-bin",
            str(FIXTURE_ROOT / "cli-v1-luna.sh"),
            "--app-codex-bin",
            str(FIXTURE_ROOT / "missing-app"),
        )
        self.assertEqual(env.returncode, 0, env.stderr)
        self.assertIn("CLI_MULTI_AGENT=true", env.stdout)
        self.assertIn("CLI_LUNA_MAX=true", env.stdout)
        self.assertIn("RECOMMENDED_PROFILE=luna-v1", env.stdout)
        self.assertIn("RECOMMENDED_PROFILE_DIAGNOSTIC_ONLY=true", env.stdout)
        self.assertIn("ROUTE_REASON='Diagnostic", env.stdout)

        v2 = run_detector(
            "--format",
            "profile",
            "--codex-bin",
            str(FIXTURE_ROOT / "cli-v2-luna.sh"),
            "--app-codex-bin",
            str(FIXTURE_ROOT / "missing-app"),
            "--native-v2-luna",
            "yes",
        )
        self.assertEqual(v2.returncode, 0, v2.stderr)
        self.assertEqual(v2.stdout.strip(), "luna-v2")


if __name__ == "__main__":
    unittest.main()
