#!/usr/bin/env python3
"""Offline behavioral coverage for the Skill forward planner."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
FORWARD_HELPER = ROOT / "payload/skills/versatile-dev/scripts/forward_router.py"
ROUTE_HELPER = ROOT / "payload/skills/versatile-dev/scripts/route_research.py"
TASK_FIXTURE = ROOT / "tests/fixtures/forward/tasks.json"
LIVE_ENTRYPOINT = ROOT / "tests/test_live_codex.sh"
LIVE_SCHEMA_FIXTURE = ROOT / "tests/fixtures/live/native-luna-schema-sample.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FORWARD = load_module("forward_router", FORWARD_HELPER)
ROUTE = load_module("route_research", ROUTE_HELPER)
CASES = json.loads(TASK_FIXTURE.read_text(encoding="utf-8"))["cases"]


def bind_route_document(document: dict[str, object], task_packet_hash: str) -> dict[str, object]:
    bound = copy.deepcopy(document)
    bound["task_packet_hash"] = task_packet_hash
    for event in bound["events"]:  # type: ignore[index]
        event["task_packet_hash"] = task_packet_hash
    return bound


def run_live(*, evidence: Path | None = None, raw: str | None = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["RUN_CODEX_LIVE"] = "1"
    with tempfile.TemporaryDirectory() as directory:
        evidence_path = Path(directory) / "evidence.json"
        if raw is not None:
            evidence_path.write_text(raw, encoding="utf-8")
        else:
            assert evidence is not None
            evidence_path.write_bytes(evidence.read_bytes())
        environment["CODEX_LIVE_EVIDENCE_FILE"] = str(evidence_path)
        return subprocess.run(
            ["bash", str(LIVE_ENTRYPOINT)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )


class ForwardRoutingTests(unittest.TestCase):
    def test_simple_task_has_no_delegated_agent(self) -> None:
        plan = FORWARD.plan_forward(CASES["simple"])
        self.assertEqual(plan["selected_agents"], [])
        self.assertEqual(plan["next_action"], "implement_directly")
        self.assertEqual(plan["writer_batches"], [])
        self.assertIsNone(plan["native_effective_route"])

    def test_docs_task_is_luna_first_and_uses_shipped_route_pins(self) -> None:
        plan = FORWARD.plan_forward(CASES["docs"])
        self.assertEqual(plan["selected_agents"], ["docs_researcher_luna"])
        self.assertEqual(plan["next_action"], "precheck")
        self.assertEqual(plan["requested_route"], {"route": "luna", **ROUTE.ROUTES["luna"]})
        self.assertEqual(plan["fallback_policy"]["max_attempts"], 1)
        self.assertEqual(plan["fallback_policy"]["permitted_failure_class"], "NATIVE_ROUTING_FAILURE")
        self.assertTrue(plan["fallback_policy"]["same_task_packet_hash"])
        for name, route_name in (("docs_researcher_luna", "luna"), ("docs_researcher_terra", "terra")):
            source = tomllib.loads(
                (ROOT / f"payload/agents/common/{name}.toml").read_text(encoding="utf-8")
            )
            self.assertEqual(
                {"agent_type": source["name"], "model": source["model"], "effort": source["model_reasoning_effort"]},
                ROUTE.ROUTES[route_name],
            )

    def test_classified_luna_route_failure_handoffs_once_to_terra_with_same_hash(self) -> None:
        packet = CASES["docs"]
        route_document = bind_route_document(json.loads(
            (ROOT / "tests/fixtures/routing/luna-mismatch.json").read_text(encoding="utf-8")
        ), packet["task_packet_hash"])
        fallback_state = ROUTE.decide(route_document)
        with mock.patch.object(
            FORWARD.route_research,
            "decide",
            wraps=FORWARD.route_research.decide,
        ) as replay:
            plan = FORWARD.forward_route(packet, route_document)
        replay.assert_called_once()
        self.assertIsNot(replay.call_args.args[0], route_document)
        self.assertEqual(replay.call_args.args[0], route_document)
        self.assertEqual(fallback_state["state"], ROUTE.STATE_FALLBACK_PENDING)
        self.assertEqual(fallback_state["next_action"], "spawn_terra")
        self.assertEqual(fallback_state["failure_class"], "NATIVE_ROUTING_FAILURE")
        self.assertEqual(fallback_state["fallback_attempt"], 1)
        self.assertEqual(plan["selected_agents"], ["docs_researcher_terra"])
        self.assertEqual(len(plan["selected_agents"]), 1)
        self.assertEqual(plan["next_action"], "spawn_terra")
        self.assertEqual(plan["fallback_attempt"], 1)
        self.assertEqual(plan["handoff"]["fallback_attempt"], 1)
        self.assertEqual(plan["handoff"]["task_packet_hash"], packet["task_packet_hash"])
        self.assertEqual(plan["handoff"]["requested_route"], {"route": "terra", **ROUTE.ROUTES["terra"]})

    def test_terminal_route_failures_never_create_a_terra_handoff(self) -> None:
        base = json.loads(
            (ROOT / "tests/fixtures/routing/luna-success.json").read_text(encoding="utf-8")
        )
        packet = CASES["docs"]
        statuses = (
            ("content_failure", "TASK_FAILURE"),
            ("tool_failure", "TASK_FAILURE"),
            ("task_failure", "TASK_FAILURE"),
            ("timeout", "TIMEOUT"),
            ("unknown_exception", "UNKNOWN_EXCEPTION"),
        )
        for status, failure_class in statuses:
            with self.subTest(status=status):
                document = bind_route_document(base, packet["task_packet_hash"])
                document["events"][1].update(
                    {"status": status, "failure_class": failure_class}
                )
                expected_state = (
                    ROUTE.STATE_STOP_UNVERIFIED
                    if status == "unknown_exception"
                    else ROUTE.STATE_STOP_FAILED
                )
                route_state = ROUTE.decide(document)
                self.assertEqual(route_state["state"], expected_state)
                self.assertTrue(route_state["terminal"])
                self.assertEqual(route_state["fallback_attempt"], 0)
                self.assertEqual(route_state["next_action"], "none")
                expected_failure_class = (
                    "UNKNOWN_EXCEPTION" if status == "unknown_exception" else
                    "TIMEOUT" if status == "timeout" else "TASK_FAILURE"
                )
                self.assertEqual(route_state["failure_class"], expected_failure_class)
                plan = FORWARD.forward_route(packet, document)
                self.assertEqual(plan["selected_agents"], [])
                self.assertEqual(plan["next_action"], "none")
                self.assertIsNone(plan["handoff"])

    def test_specialist_selection_is_exactly_one_required_role(self) -> None:
        expected = {
            "cuda": "gpu_reviewer",
            "numerical": "numerics_reviewer",
            "security": "security_reviewer",
        }
        for task_kind, role in expected.items():
            with self.subTest(task_kind=task_kind):
                plan = FORWARD.plan_forward(CASES[task_kind])
                self.assertEqual(plan["selected_agents"], [role])
                self.assertEqual(plan["next_action"], "run_required_specialist")
                self.assertIsNone(plan["requested_route"])

    def test_shared_file_writers_are_serialized_but_disjoint_writers_share_a_batch(self) -> None:
        plan = FORWARD.plan_forward(CASES["shared_writers"])
        self.assertEqual(
            plan["writer_batches"],
            [["implementer"], ["tester"]],
        )
        disjoint = FORWARD.plan_forward(CASES["disjoint_writers"])
        self.assertEqual(disjoint["writer_batches"], [["implementer", "tester"]])

    def test_app_task_requires_current_request_authorization_not_configuration(self) -> None:
        unauthorized = FORWARD.plan_forward(CASES["app_unauthorized"])
        self.assertEqual(unauthorized["app_task"]["allowed"], False)
        self.assertEqual(unauthorized["app_task"]["next_action"], "stop_unverified")
        self.assertEqual(
            unauthorized["app_task"]["reason"],
            "app_task_requires_explicit_current_request_authorization",
        )
        self.assertIsNone(unauthorized["native_effective_route"])

        authorized = FORWARD.plan_forward(CASES["app_authorized"])
        self.assertEqual(authorized["app_task"]["allowed"], True)
        self.assertEqual(authorized["app_task"]["next_action"], "create_app_task")
        self.assertIsNone(authorized["native_effective_route"])

        missing_authorization = copy.deepcopy(CASES["app_unauthorized"])
        del missing_authorization["app_task"]["current_request_authorized"]
        with self.assertRaises(FORWARD.ForwardRouteError):
            FORWARD.plan_forward(missing_authorization)

    def test_canonical_packet_hash_binds_body_and_validation_returns_defensive_copy(self) -> None:
        packet = CASES["simple"]
        self.assertEqual(FORWARD.canonical_packet_hash(packet), packet["task_packet_hash"])
        hash_member_change = copy.deepcopy(packet)
        hash_member_change["task_packet_hash"] = "sha256:" + "0" * 64
        self.assertEqual(FORWARD.canonical_packet_hash(hash_member_change), packet["task_packet_hash"])

        validated = FORWARD.validate_packet(packet)
        validated["app_task"]["configured_route"] = "mutated"  # type: ignore[index]
        self.assertEqual(packet["app_task"]["configured_route"], "unknown")
        with self.assertRaises(FORWARD.ForwardRouteError):
            FORWARD.validate_packet({**packet, "request": "changed body"})

    def test_route_handoff_rejects_changed_packet_hash_and_route_document_hash(self) -> None:
        route_document = bind_route_document(json.loads(
            (ROOT / "tests/fixtures/routing/luna-mismatch.json").read_text(encoding="utf-8")
        ), CASES["docs"]["task_packet_hash"])
        packet = copy.deepcopy(CASES["docs"])
        packet["request"] = "changed body"
        self.assertNotEqual(packet, CASES["docs"])
        with self.assertRaises(FORWARD.ForwardRouteError):
            FORWARD.forward_route(packet, route_document)
        unbound_document = json.loads(
            (ROOT / "tests/fixtures/routing/luna-mismatch.json").read_text(encoding="utf-8")
        )
        with self.assertRaises(FORWARD.ForwardRouteError):
            FORWARD.forward_route(CASES["docs"], unbound_document)

    def test_route_handoff_requires_full_route_document_and_replayed_classification(self) -> None:
        route_document = bind_route_document(json.loads(
            (ROOT / "tests/fixtures/routing/luna-mismatch.json").read_text(encoding="utf-8")
        ), CASES["docs"]["task_packet_hash"])
        forged_summary = {
            "state": ROUTE.STATE_FALLBACK_PENDING,
            "failure_class": "NATIVE_ROUTING_FAILURE",
            "fallback_attempt": 1,
            "task_packet_hash": CASES["docs"]["task_packet_hash"],
        }
        with self.assertRaises(FORWARD.ForwardRouteError):
            FORWARD.forward_route(CASES["docs"], forged_summary)

        conflicting_document = copy.deepcopy(route_document)
        conflicting_document["events"][1]["failure_class"] = "TASK_FAILURE"
        self.assertNotEqual(conflicting_document, route_document)
        conflicting_state = ROUTE.decide(conflicting_document)
        self.assertEqual(conflicting_state["state"], ROUTE.STATE_STOP_UNVERIFIED)
        conflicting_plan = FORWARD.forward_route(CASES["docs"], conflicting_document)
        self.assertEqual(conflicting_plan["next_action"], "none")
        self.assertIsNone(conflicting_plan["handoff"])

        invalid_count_document = copy.deepcopy(route_document)
        invalid_count_document["events"][1]["fallback_attempt"] = 1
        self.assertNotEqual(invalid_count_document, route_document)
        with self.assertRaises(FORWARD.ForwardRouteError):
            FORWARD.forward_route(CASES["docs"], invalid_count_document)

    def test_packet_paths_are_canonical_and_writers_are_owned(self) -> None:
        invalid_paths = (
            "/tmp/file.py",
            "./tests/test.py",
            "../tests/test.py",
            "src//file.py",
            "src/../file.py",
            "src\\file.py",
            "",
            ".",
            "tests/file.py/",
            "tests/e\u0301.py",
        )
        for path in invalid_paths:
            with self.subTest(path=repr(path)):
                packet = copy.deepcopy(CASES["simple"])
                packet["files"] = [path]
                self.assertNotEqual(packet, CASES["simple"])
                with self.assertRaises(FORWARD.ForwardRouteError):
                    FORWARD.validate_packet(packet)

        aliases = (
            ("tests/A.py", "tests/a.py"),
            ("tests/Straße.py", "tests/STRASSE.py"),
        )
        for first, second in aliases:
            with self.subTest(alias=(first, second)):
                packet = copy.deepcopy(CASES["simple"])
                packet["files"] = [first, second]
                self.assertNotEqual(packet, CASES["simple"])
                with self.assertRaisesRegex(
                    FORWARD.ForwardRouteError,
                    "portable path aliases",
                ):
                    FORWARD.validate_packet(packet)

        cases = (
            {"writer_id": "implementer", "files": ["src/not-listed.py"]},
            {"writer_id": "tester", "files": ["src/implementation.py"]},
            {"writer_id": "performance_profiler", "files": ["src/profile.py"]},
            {"writer_id": "implementer", "files": ["src/a.py", "src/a.py"]},
            {"writer_id": "implementer", "files": ["tests/A.py", "tests/a.py"]},
        )
        for writer in cases:
            with self.subTest(writer=writer):
                packet = copy.deepcopy(CASES["simple"])
                packet["files"] = ["src/implementation.py", "tests/test.py"]
                packet["writers"] = [writer]
                self.assertNotEqual(packet, CASES["simple"])
                with self.assertRaises(FORWARD.ForwardRouteError):
                    FORWARD.validate_packet(packet)

    def test_writer_overlap_uses_nfc_casefold_collision_key_defensively(self) -> None:
        self.assertEqual(
            FORWARD.portable_collision_key("tests/Straße.py"),
            FORWARD.portable_collision_key("tests/STRASSE.py"),
        )
        self.assertNotEqual(
            FORWARD.portable_collision_key("tests/alpha.py"),
            FORWARD.portable_collision_key("tests/beta.py"),
        )

        ascii_aliases = [
            {"writer_id": "implementer", "files": ["tests/A.py"]},
            {"writer_id": "tester", "files": ["tests/a.py"]},
        ]
        unicode_aliases = [
            {"writer_id": "implementer", "files": ["tests/Straße.py"]},
            {"writer_id": "tester", "files": ["tests/STRASSE.py"]},
        ]
        for writers in (ascii_aliases, unicode_aliases):
            with self.subTest(writers=writers):
                self.assertEqual(FORWARD._writer_batches(writers), [["implementer"], ["tester"]])

        distinct = [
            {"writer_id": "implementer", "files": ["tests/alpha.py"]},
            {"writer_id": "tester", "files": ["tests/beta.py"]},
        ]
        self.assertEqual(FORWARD._writer_batches(distinct), [["implementer", "tester"]])

    def test_cli_plan_replay_and_duplicate_json_inputs_are_strict(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        plan_process = subprocess.run(
            [sys.executable, str(FORWARD_HELPER), "plan", "-"],
            cwd=ROOT,
            env=environment,
            input=json.dumps(CASES["simple"]),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(plan_process.returncode, 0, plan_process.stderr)
        self.assertEqual(json.loads(plan_process.stdout)["next_action"], "implement_directly")

        route_document = bind_route_document(json.loads(
            (ROOT / "tests/fixtures/routing/luna-mismatch.json").read_text(encoding="utf-8")
        ), CASES["docs"]["task_packet_hash"])
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            packet_path = directory_path / "packet.json"
            route_path = directory_path / "route.json"
            packet_path.write_text(json.dumps(CASES["docs"]), encoding="utf-8")
            route_path.write_text(json.dumps(route_document), encoding="utf-8")
            replay_process = subprocess.run(
                [sys.executable, str(FORWARD_HELPER), "replay", str(packet_path), str(route_path)],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(replay_process.returncode, 0, replay_process.stderr)
            self.assertEqual(json.loads(replay_process.stdout)["next_action"], "spawn_terra")

            duplicate_packet = directory_path / "duplicate-packet.json"
            duplicate_packet.write_text(
                '{"schema_version":1,"schema_version":1}', encoding="utf-8"
            )
            duplicate_process = subprocess.run(
                [sys.executable, str(FORWARD_HELPER), "plan", str(duplicate_packet)],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(duplicate_process.returncode, 2)
            self.assertEqual(duplicate_process.stdout, "")
            self.assertIn("duplicate JSON member", duplicate_process.stderr)

            duplicate_route = directory_path / "duplicate-route.json"
            route_text = json.dumps(route_document)
            duplicate_route.write_text(
                route_text.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1', 1),
                encoding="utf-8",
            )
            duplicate_route_process = subprocess.run(
                [sys.executable, str(FORWARD_HELPER), "replay", str(packet_path), str(duplicate_route)],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(duplicate_route_process.returncode, 2)
            self.assertEqual(duplicate_route_process.stdout, "")
            self.assertIn("duplicate JSON member", duplicate_route_process.stderr)

            for first, second in (("tests/A.py", "tests/a.py"), ("tests/Straße.py", "tests/STRASSE.py")):
                with self.subTest(cli_alias=(first, second)):
                    alias_packet = copy.deepcopy(CASES["simple"])
                    alias_packet["files"] = [first, second]
                    alias_path = directory_path / "portable-alias-packet.json"
                    alias_path.write_text(
                        json.dumps(alias_packet, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    alias_process = subprocess.run(
                        [sys.executable, str(FORWARD_HELPER), "plan", str(alias_path)],
                        cwd=ROOT,
                        env=environment,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertNotEqual(alias_packet, CASES["simple"])
                    self.assertEqual(alias_process.returncode, 2)
                    self.assertEqual(alias_process.stdout, "")
                    self.assertIn("portable path aliases", alias_process.stderr)

    def test_workflow_references_the_offline_helper_after_parent_classification(self) -> None:
        workflow = (ROOT / "payload/skills/versatile-dev/references/workflow.md").read_text(
            encoding="utf-8"
        )
        for phrase in (
            "forward_router.py",
            "parent has explicitly classified",
            "plan",
            "replay",
            "never classifies English",
            "native spawn",
            "App actions remain parent Skill authority",
        ):
            self.assertIn(phrase, workflow)

    def test_offline_gate_excludes_optional_live_entrypoint_exactly(self) -> None:
        run_script = (ROOT / "tests/run.sh").read_text(encoding="utf-8")
        package_script = (ROOT / "package.sh").read_text(encoding="utf-8")
        self.assertIn("test_forward_routing.py", run_script)
        self.assertNotIn("test_live_codex.sh", run_script)
        self.assertNotIn("RUN_CODEX_LIVE", run_script)
        self.assertNotIn("test_live_codex.sh", package_script)
        self.assertNotIn("RUN_CODEX_LIVE", package_script)
        self.assertTrue(LIVE_ENTRYPOINT.exists())
        self.assertTrue(LIVE_SCHEMA_FIXTURE.exists())
        self.assertFalse((ROOT / "tests/fixtures/live/native-luna-conformance.json").exists())

    def test_live_entrypoint_is_disabled_by_default_and_schema_sample_is_unverified(self) -> None:
        disabled = subprocess.run(
            ["bash", str(LIVE_ENTRYPOINT)],
            cwd=ROOT,
            env={**os.environ, "RUN_CODEX_LIVE": "0"},
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(disabled.returncode, 0)
        self.assertIn("SKIP:", disabled.stdout)
        self.assertEqual(disabled.stderr, "")

        enabled = run_live(evidence=LIVE_SCHEMA_FIXTURE)
        output = enabled.stdout + enabled.stderr
        self.assertEqual(enabled.returncode, 2)
        self.assertIn(
            "UNVERIFIED: schema-valid evidence is not authenticated fresh live conformance",
            output,
        )
        self.assertNotIn("CONFORMANCE VERIFIED", output)

    def test_live_entrypoint_rejects_forged_or_sensitive_evidence_without_echoing_values(self) -> None:
        source = json.loads(LIVE_SCHEMA_FIXTURE.read_text(encoding="utf-8"))
        mutations = (
            ("configured_model", lambda attempt: attempt.update({"configured_model": "gpt-4.1"})),
            ("status", lambda attempt: attempt.update({"status": "timeout", "failure_class": "TIMEOUT"})),
            ("fallback", lambda attempt: attempt.update({"fallback_attempt": 1})),
            ("interface", lambda attempt: attempt.update({"interface": "fake_spawn"})),
            ("runtime", lambda attempt: attempt["evidence_source"].update({"runtime_id": "other-runtime"})),
            ("attempt", lambda attempt: attempt["evidence_source"].update({"attempt_id": "other-attempt"})),
            ("task_hash", lambda attempt: attempt.update({"task_packet_hash": "sha256:" + "4" * 64})),
            ("secret", lambda attempt: attempt.update({"permission_profile": "token=super-secret"})),
            ("newline", lambda attempt: attempt.update({"permission_profile": "default\ninjected"})),
            ("unknown_member", lambda attempt: attempt.update({"unexpected": "value"})),
        )
        for name, mutation in mutations:
            with self.subTest(mutation=name):
                candidate = copy.deepcopy(source)
                mutation(candidate["audit"]["attempt"])
                self.assertNotEqual(candidate, source)
                result = run_live(raw=json.dumps(candidate))
                output = result.stdout + result.stderr
                self.assertEqual(result.returncode, 2)
                self.assertIn("UNVERIFIED:", output)
                self.assertNotIn("CONFORMANCE VERIFIED", output)
                self.assertNotIn("super-secret", output)

    def test_live_entrypoint_rejects_duplicate_members_at_load_boundary(self) -> None:
        raw = LIVE_SCHEMA_FIXTURE.read_text(encoding="utf-8")
        duplicate = raw.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1', 1)
        result = run_live(raw=duplicate)
        self.assertEqual(result.returncode, 2)
        self.assertIn("UNVERIFIED:", result.stdout + result.stderr)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
