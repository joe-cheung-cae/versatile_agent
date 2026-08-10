#!/usr/bin/env python3
"""Focused offline coverage for the deterministic route state machine."""

from __future__ import annotations

import importlib.util
import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "payload/skills/versatile-dev/scripts/route_research.py"
FIXTURE_ROOT = ROOT / "tests/fixtures/routing"
RUNTIME_FIXTURE_ROOT = ROOT / "tests/fixtures/runtime"
SPEC = importlib.util.spec_from_file_location("route_research", HELPER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to load {HELPER}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def read_fixture(name: str) -> dict:
    path = FIXTURE_ROOT / name
    if not path.exists():
        path = RUNTIME_FIXTURE_ROOT / name
    return json.loads(path.read_text(encoding="utf-8"))


HASH = "sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"
ACTIVE_RUNTIME_ID = "fixture-active-interface"


def active_interface_record() -> dict:
    record = copy.deepcopy(read_fixture("native-spawn.json")["records"][0])
    record.pop("observed", None)
    record["runtime_id"] = ACTIVE_RUNTIME_ID
    record["evidence_source"]["runtime_id"] = ACTIVE_RUNTIME_ID
    return record


def route_document(runtime_fixture: str, events: list[dict], *, task_hash: str = HASH) -> dict:
    runtime_records = read_fixture(runtime_fixture)
    if runtime_records.get("records", [{}])[0].get("interface_kind") == "native_spawn_attempt":
        runtime_records["records"].insert(0, active_interface_record())
    return {
        "events": events,
        "runtime_records": runtime_records,
        "schema_version": 1,
        "task_packet_hash": task_hash,
    }


def precheck(runtime_id: str = ACTIVE_RUNTIME_ID, *, task_hash: str = HASH, fallback_attempt: int = 0) -> dict:
    return {
        "event": "precheck",
        "fallback_attempt": fallback_attempt,
        "runtime_id": runtime_id,
        "task_packet_hash": task_hash,
    }


def result_event(
    event_name: str,
    runtime_id: str,
    attempt_id: str,
    status: str,
    failure_class: str,
    *,
    task_hash: str = HASH,
    fallback_attempt: int = 0,
    precheck_runtime_id: str = ACTIVE_RUNTIME_ID,
    **extra: object,
) -> dict:
    return {
        "attempt_id": attempt_id,
        "event": event_name,
        "failure_class": failure_class,
        "fallback_attempt": fallback_attempt,
        "precheck_runtime_id": precheck_runtime_id,
        "runtime_id": runtime_id,
        "status": status,
        "task_packet_hash": task_hash,
        **extra,
    }


def terra_dispatch(
    runtime_id: str,
    *,
    task_hash: str = HASH,
    attempt_id: str = "terra-1",
    precheck_runtime_id: str = ACTIVE_RUNTIME_ID,
) -> dict:
    return {
        "attempt_id": attempt_id,
        "event": "dispatch_terra",
        "fallback_attempt": 1,
        "precheck_runtime_id": precheck_runtime_id,
        "runtime_id": runtime_id,
        "task_packet_hash": task_hash,
    }


def explicit_rejection_document(trigger: str) -> dict:
    runtime = read_fixture("native-request-only.json")
    attempt = runtime["records"][0]
    attempt_runtime_id = f"fixture-{trigger}-attempt"
    attempt["runtime_id"] = attempt_runtime_id
    attempt["evidence_source"]["runtime_id"] = attempt_runtime_id
    if trigger == "requested_agent_unavailable":
        attempt["exposed_agent_types"] = []
    elif trigger == "requested_model_unavailable":
        attempt["model_support"] = []
        attempt["effort_support"] = {}
    elif trigger == "requested_effort_unsupported":
        attempt["model_support"] = ["gpt-5.6-luna"]
        attempt["effort_support"] = {"gpt-5.6-luna": ["low"]}
    runtime["records"].insert(0, active_interface_record())
    event = result_event(
        "luna_result",
        attempt_runtime_id,
        "luna-1",
        "routing_failure",
        "NATIVE_ROUTING_FAILURE",
        routing_failure=trigger,
        routing_evidence={
            "attempt_id": "luna-1",
            "detail": f"same-attempt evidence for {trigger}",
            "kind": trigger,
            "runtime_id": attempt_runtime_id,
        },
    )
    return {
        "events": [precheck(), event],
        "runtime_records": runtime,
        "schema_version": 1,
        "task_packet_hash": HASH,
    }


class RoutingStateTests(unittest.TestCase):
    def test_luna_success_replays_to_done_luna(self) -> None:
        result = MODULE.decide(read_fixture("luna-success.json"))
        self.assertEqual(result["state"], MODULE.STATE_DONE_LUNA)
        self.assertEqual(result["next_action"], "none")
        self.assertTrue(result["terminal"])
        self.assertEqual(result["fallback_attempt"], 0)
        self.assertEqual(result["failure_class"], "NONE")
        self.assertEqual(result["precheck_runtime_id"], ACTIVE_RUNTIME_ID)
        self.assertEqual(result["effective_route"]["model"], "gpt-5.6-luna")

    def test_empty_replay_waits_for_precheck(self) -> None:
        document = route_document("native-spawn.json", [])
        result = MODULE.decide(document)
        self.assertEqual(result["state"], MODULE.STATE_PRECHECK)
        self.assertEqual(result["next_action"], "precheck")
        self.assertFalse(result["terminal"])

    def test_precheck_requires_one_same_record_dual_native_exposure(self) -> None:
        base = read_fixture("native-spawn.json")
        cases = {
            "unknown": "unknown",
            "empty": [],
            "one": ["docs_researcher_luna"],
        }
        for name, exposure in cases.items():
            with self.subTest(name=name):
                runtime = copy.deepcopy(base)
                runtime["records"].insert(0, active_interface_record())
                runtime["records"][0]["exposed_agent_types"] = exposure
                result = MODULE.decide(route_document("native-spawn.json", [precheck()]) | {"runtime_records": runtime})
                self.assertEqual(result["state"], MODULE.STATE_STOP_UNVERIFIED)
                self.assertEqual(result["next_action"], "none")

        for generation in ("v1", "none", "unknown"):
            with self.subTest(generation=generation):
                runtime = copy.deepcopy(base)
                runtime["records"].insert(0, active_interface_record())
                runtime["records"][0]["multi_agent_generation"] = generation
                result = MODULE.decide(route_document("native-spawn.json", [precheck()]) | {"runtime_records": runtime})
                self.assertEqual(result["state"], MODULE.STATE_STOP_UNVERIFIED)

    def test_precheck_rejects_diagnostic_wrong_interface_and_complementary_app_evidence(self) -> None:
        diagnostic = read_fixture("native-spawn.json")
        diagnostic["records"].insert(0, active_interface_record())
        diagnostic["records"][0]["diagnostic_only"] = True
        result = route_document("native-spawn.json", [precheck()])
        result["runtime_records"] = diagnostic
        self.assertEqual(MODULE.decide(result)["state"], MODULE.STATE_STOP_UNVERIFIED)

        app_document = read_fixture("app-task.json")
        app_document["records"][0]["exposed_agent_types"] = [
            "docs_researcher_luna",
            "docs_researcher_terra",
        ]
        app_result = route_document("app-task.json", [precheck("fixture-app-task-luna")])
        app_result["runtime_records"] = app_document
        self.assertEqual(MODULE.decide(app_result)["state"], MODULE.STATE_STOP_UNVERIFIED)

        complementary = route_document(
            "cli-and-app-records.json",
            [precheck("fixture-app-luna-only")],
        )
        complementary_result = MODULE.decide(complementary)
        self.assertEqual(complementary_result["state"], MODULE.STATE_STOP_UNVERIFIED)

    def test_each_allowed_luna_routing_failure_authorizes_one_fallback(self) -> None:
        rejection_triggers = (
            "requested_agent_unavailable",
            "requested_model_unavailable",
            "model_access_denied",
            "requested_effort_unsupported",
            "native_spawn_rejected",
        )
        for trigger in rejection_triggers:
            with self.subTest(trigger=trigger):
                result = MODULE.decide(explicit_rejection_document(trigger))
                self.assertEqual(result["state"], MODULE.STATE_FALLBACK_PENDING)
                self.assertEqual(result["next_action"], "spawn_terra")
                self.assertEqual(result["fallback_attempt"], 1)

        mismatch = MODULE.decide(read_fixture("luna-mismatch.json"))
        self.assertEqual(mismatch["state"], MODULE.STATE_FALLBACK_PENDING)
        self.assertEqual(mismatch["reason"], "luna_native_route_mismatch")
        self.assertEqual(mismatch["fallback_attempt"], 1)

    def test_unavailable_capability_present_conflicts_with_trigger(self) -> None:
        mutations = {
            "requested_agent_unavailable": lambda record: record.update(
                {"exposed_agent_types": ["docs_researcher_luna"]}
            ),
            "requested_model_unavailable": lambda record: record.update(
                {"model_support": ["gpt-5.6-luna"]}
            ),
            "requested_effort_unsupported": lambda record: record.update(
                {
                    "model_support": ["gpt-5.6-luna"],
                    "effort_support": {"gpt-5.6-luna": ["max"]},
                }
            ),
        }
        for trigger, mutation in mutations.items():
            with self.subTest(trigger=trigger):
                document = explicit_rejection_document(trigger)
                attempt = next(
                    record
                    for record in document["runtime_records"]["records"]
                    if record["runtime_id"] == f"fixture-{trigger}-attempt"
                )
                mutation(attempt)
                result = MODULE.decide(document)
                self.assertEqual(result["state"], MODULE.STATE_STOP_UNVERIFIED)
                self.assertEqual(result["fallback_attempt"], 0)

    def test_diagnostic_attempt_cannot_prove_success_or_fallback(self) -> None:
        success = read_fixture("luna-success.json")
        next(
            record
            for record in success["runtime_records"]["records"]
            if record["runtime_id"] == "fixture-luna-attempt"
        )["diagnostic_only"] = True
        success_result = MODULE.decide(success)
        self.assertEqual(success_result["state"], MODULE.STATE_STOP_UNVERIFIED)
        self.assertEqual(success_result["fallback_attempt"], 0)

        rejection = explicit_rejection_document("native_spawn_rejected")
        next(
            record
            for record in rejection["runtime_records"]["records"]
            if record["runtime_id"] == "fixture-native_spawn_rejected-attempt"
        )["diagnostic_only"] = True
        rejection_result = MODULE.decide(rejection)
        self.assertEqual(rejection_result["state"], MODULE.STATE_STOP_UNVERIFIED)
        self.assertEqual(rejection_result["fallback_attempt"], 0)

    def test_routing_rejection_requires_same_attempt_evidence(self) -> None:
        missing = read_fixture("luna-routing-rejection.json")
        missing["events"][1].pop("routing_evidence")
        with self.assertRaises(MODULE.RouteResearchError):
            MODULE.decide(missing)

        wrong_runtime = read_fixture("luna-routing-rejection.json")
        wrong_runtime["events"][1]["routing_evidence"]["runtime_id"] = "other-runtime"
        result = MODULE.decide(wrong_runtime)
        self.assertEqual(result["state"], MODULE.STATE_STOP_UNVERIFIED)

        non_routing_metadata = read_fixture("luna-success.json")
        non_routing_metadata["events"][1]["routing_failure"] = "native_spawn_rejected"
        non_routing_metadata["events"][1]["routing_evidence"] = {
            "attempt_id": "luna-1",
            "detail": "conflicting metadata",
            "kind": "native_spawn_rejected",
            "runtime_id": "fixture-luna-attempt",
        }
        result = MODULE.decide(non_routing_metadata)
        self.assertEqual(result["state"], MODULE.STATE_STOP_UNVERIFIED)

        mismatch_metadata = read_fixture("luna-mismatch.json")
        mismatch_metadata["events"][1]["routing_failure"] = "native_route_mismatch"
        mismatch_metadata["events"][1]["routing_evidence"] = {
            "attempt_id": "luna-1",
            "detail": "synthetic evidence is forbidden for mismatch",
            "kind": "native_spawn_rejected",
            "runtime_id": "fixture-luna-mismatch-attempt",
        }
        result = MODULE.decide(mismatch_metadata)
        self.assertEqual(result["state"], MODULE.STATE_STOP_UNVERIFIED)

    def test_rejection_trigger_unknown_capability_facts_fail_closed(self) -> None:
        for trigger, mutation in (
            (
                "requested_agent_unavailable",
                lambda record: record.update({"exposed_agent_types": "unknown"}),
            ),
            (
                "requested_model_unavailable",
                lambda record: record.update({"model_support": "unknown", "effort_support": "unknown"}),
            ),
            (
                "requested_effort_unsupported",
                lambda record: record.update({"effort_support": "unknown"}),
            ),
        ):
            with self.subTest(trigger=trigger):
                document = explicit_rejection_document(trigger)
                attempt = next(
                    record
                    for record in document["runtime_records"]["records"]
                    if record["runtime_id"] == f"fixture-{trigger}-attempt"
                )
                mutation(attempt)
                result = MODULE.decide(document)
                self.assertEqual(result["state"], MODULE.STATE_STOP_UNVERIFIED)

        complete = explicit_rejection_document("model_access_denied")
        attempt = next(
            record
            for record in complete["runtime_records"]["records"]
            if record["runtime_id"] == "fixture-model_access_denied-attempt"
        )
        attempt["observed"].update(
            {
                "effective_agent_type": "docs_researcher_luna",
                "effective_effort": "max",
                "effective_model": "gpt-5.6-luna",
            }
        )
        result = MODULE.decide(complete)
        self.assertEqual(result["state"], MODULE.STATE_STOP_UNVERIFIED)

    def test_content_tool_task_timeout_and_unknown_failures_never_fallback(self) -> None:
        cases = (
            ("content_failure", "TASK_FAILURE"),
            ("tool_failure", "TASK_FAILURE"),
            ("task_failure", "TASK_FAILURE"),
            ("timeout", "TIMEOUT"),
        )
        for status, failure_class in cases:
            with self.subTest(status=status):
                document = route_document(
                    "native-spawn.json",
                    [
                        precheck(),
                        result_event(
                            "luna_result",
                            "fixture-native-luna-attempt",
                            "luna-1",
                            status,
                            failure_class,
                        ),
                    ],
                )
                result = MODULE.decide(document)
                self.assertEqual(result["state"], MODULE.STATE_STOP_FAILED)
                self.assertEqual(result["fallback_attempt"], 0)
                self.assertEqual(result["failure_class"], failure_class)

        unknown = MODULE.decide(
            route_document(
                "native-spawn.json",
                [
                    precheck(),
                    result_event(
                        "luna_result",
                        "fixture-native-luna-attempt",
                        "luna-1",
                        "unknown_exception",
                        "UNKNOWN_EXCEPTION",
                    ),
                ],
            )
        )
        self.assertEqual(unknown["state"], MODULE.STATE_STOP_UNVERIFIED)
        self.assertEqual(unknown["failure_class"], "UNKNOWN_EXCEPTION")
        self.assertEqual(unknown["fallback_attempt"], 0)

    def test_incomplete_noncanonical_and_conflicting_effective_metadata_stop_unverified(self) -> None:
        for fixture in (
            "native-request-only.json",
            "native-effective-unknown.json",
            "native-partial-effective-mismatch.json",
            "native-whitespace-effective.json",
            "native-padded-effective.json",
            "native-effective-support-conflict.json",
        ):
            with self.subTest(fixture=fixture):
                runtime = read_fixture(fixture)
                runtime["records"].insert(0, active_interface_record())
                runtime["records"][0]["exposed_agent_types"] = [
                    "docs_researcher_luna",
                    "docs_researcher_terra",
                ]
                document = route_document(
                    fixture,
                    [
                        precheck(),
                        result_event(
                            "luna_result",
                            runtime["records"][0]["runtime_id"],
                            "luna-1",
                            "task_success",
                            "NONE",
                        ),
                    ],
                )
                document["runtime_records"] = runtime
                result = MODULE.decide(document)
                self.assertEqual(result["state"], MODULE.STATE_STOP_UNVERIFIED)
                self.assertEqual(result["next_action"], "none")

    def test_attempt_bindings_fail_closed(self) -> None:
        wrong_precheck = read_fixture("luna-success.json")
        wrong_precheck["events"][1]["precheck_runtime_id"] = "other-active-interface"
        self.assertEqual(MODULE.decide(wrong_precheck)["state"], MODULE.STATE_STOP_UNVERIFIED)

        wrong_runtime = read_fixture("terra-success.json")
        terra_record = next(
            record
            for record in wrong_runtime["runtime_records"]["records"]
            if record["runtime_id"] == "fixture-terra-attempt"
        )
        replacement = copy.deepcopy(terra_record)
        replacement["runtime_id"] = "fixture-terra-other-attempt"
        replacement["evidence_source"]["runtime_id"] = "fixture-terra-other-attempt"
        wrong_runtime["runtime_records"]["records"].append(replacement)
        wrong_runtime["events"][-1]["runtime_id"] = "fixture-terra-other-attempt"
        self.assertEqual(MODULE.decide(wrong_runtime)["state"], MODULE.STATE_STOP_UNVERIFIED)

        wrong_attempt = read_fixture("terra-success.json")
        wrong_attempt["events"][-1]["attempt_id"] = "terra-2"
        self.assertEqual(MODULE.decide(wrong_attempt)["state"], MODULE.STATE_STOP_UNVERIFIED)

    def test_requested_route_fields_are_independent_required_evidence(self) -> None:
        for field, value in (
            ("agent_type", None),
            ("agent_type", "unknown"),
            ("model", " gpt-5.6-luna"),
            ("effort", "high"),
        ):
            with self.subTest(route="luna", field=field, value=value):
                document = read_fixture("luna-success.json")
                attempt = next(
                    record
                    for record in document["runtime_records"]["records"]
                    if record["runtime_id"] == "fixture-luna-attempt"
                )
                if value is None:
                    attempt["observed"].pop(field)
                else:
                    attempt["observed"][field] = value
                result = MODULE.decide(document)
                self.assertEqual(result["state"], MODULE.STATE_STOP_UNVERIFIED)

        for field, value in (
            ("agent_type", None),
            ("agent_type", "unknown"),
            ("model", " gpt-5.6-terra"),
            ("effort", "max"),
        ):
            with self.subTest(route="terra", field=field, value=value):
                document = read_fixture("terra-success.json")
                attempt = next(
                    record
                    for record in document["runtime_records"]["records"]
                    if record["runtime_id"] == "fixture-terra-attempt"
                )
                if value is None:
                    attempt["observed"].pop(field)
                else:
                    attempt["observed"][field] = value
                # The same selected native attempt record is bound to both
                # Terra dispatch and result.  Invalid requested fields must
                # fail closed at dispatch, so do not replay a later result.
                document["events"] = document["events"][:3]
                result = MODULE.decide(document)
                self.assertEqual(result["state"], MODULE.STATE_STOP_UNVERIFIED)

    def test_terra_dispatch_and_success_are_single_fallback_stack(self) -> None:
        result = MODULE.decide(read_fixture("terra-success.json"))
        self.assertEqual(result["state"], MODULE.STATE_DONE_TERRA)
        self.assertEqual(result["fallback_attempt"], 1)
        self.assertEqual(result["requested_route"]["agent_type"], "docs_researcher_terra")
        self.assertEqual(result["effective_route"]["agent_type"], "docs_researcher_terra")

        second_dispatch = read_fixture("luna-mismatch.json")
        second_dispatch["events"].extend(
            [
                terra_dispatch("fixture-terra-attempt"),
                terra_dispatch("fixture-terra-attempt", attempt_id="terra-2"),
            ]
        )
        with self.assertRaises(MODULE.RouteResearchError):
            MODULE.decide(second_dispatch)

        terra_failure = read_fixture("terra-success.json")
        terra_failure["events"][-1]["status"] = "tool_failure"
        terra_failure["events"][-1]["failure_class"] = "TASK_FAILURE"
        failure_result = MODULE.decide(terra_failure)
        self.assertEqual(failure_result["state"], MODULE.STATE_STOP_FAILED)
        self.assertEqual(failure_result["fallback_attempt"], 1)

        terra_mismatch = read_fixture("terra-success.json")
        terra_record = next(
            record
            for record in terra_mismatch["runtime_records"]["records"]
            if record["runtime_id"] == "fixture-terra-attempt"
        )
        terra_record["observed"] = {
            "agent_type": "docs_researcher_terra",
            "effort": "high",
            "model": "gpt-5.6-terra",
            "effective_agent_type": "docs_researcher_luna",
            "effective_effort": "max",
            "effective_model": "gpt-5.6-luna",
        }
        terra_record["exposed_agent_types"] = ["docs_researcher_luna", "docs_researcher_terra"]
        mismatch_result = MODULE.decide(terra_mismatch)
        self.assertEqual(mismatch_result["state"], MODULE.STATE_STOP_FAILED)
        self.assertEqual(mismatch_result["next_action"], "none")

        terra_rejection = read_fixture("terra-success.json")
        terra_record = next(
            record
            for record in terra_rejection["runtime_records"]["records"]
            if record["runtime_id"] == "fixture-terra-attempt"
        )
        terra_record["observed"] = {
            "agent_type": "docs_researcher_terra",
            "effort": "high",
            "model": "gpt-5.6-terra",
        }
        terra_rejection["events"][-1].update(
            {
                "failure_class": "NATIVE_ROUTING_FAILURE",
                "routing_failure": "native_spawn_rejected",
                "routing_evidence": {
                    "attempt_id": "terra-1",
                    "detail": "same-attempt Terra rejection",
                    "kind": "native_spawn_rejected",
                    "runtime_id": "fixture-terra-attempt",
                },
                "status": "routing_failure",
            }
        )
        rejection_result = MODULE.decide(terra_rejection)
        self.assertEqual(rejection_result["state"], MODULE.STATE_STOP_FAILED)
        self.assertEqual(rejection_result["fallback_attempt"], 1)
        self.assertEqual(rejection_result["next_action"], "none")
        self.assertTrue(rejection_result["terminal"])

    def test_hash_event_and_schema_boundaries_fail_without_tracebacks(self) -> None:
        changed_hash = read_fixture("luna-success.json")
        changed_hash["events"][1]["task_packet_hash"] = "sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
        with self.assertRaises(MODULE.RouteResearchError):
            MODULE.decide(changed_hash)

        for bad_hash in (
            "",
            " unknown",
            "unknown",
            "sha256:" + "a" * 63,
            "sha256:" + "A" * 64,
            "sha256:" + "g" * 64,
            "sha256:" + "a" * 64 + " ",
            None,
            1,
        ):
            with self.subTest(bad_hash=bad_hash):
                document = read_fixture("luna-success.json")
                document["task_packet_hash"] = bad_hash
                with self.assertRaises(MODULE.RouteResearchError):
                    MODULE.decide(document)

        missing_event_hash = read_fixture("luna-success.json")
        missing_event_hash["events"][0].pop("task_packet_hash")
        with self.assertRaises(MODULE.RouteResearchError):
            MODULE.decide(missing_event_hash)

        extra = read_fixture("luna-success.json")
        extra["unexpected"] = True
        with self.assertRaises(MODULE.RouteResearchError):
            MODULE.decide(extra)

        unknown_event = read_fixture("luna-success.json")
        unknown_event["events"][0]["event"] = "spawn_luna"
        with self.assertRaises(MODULE.RouteResearchError):
            MODULE.decide(unknown_event)

        counter = read_fixture("luna-mismatch.json")
        counter["events"][1]["fallback_attempt"] = 2
        with self.assertRaises(MODULE.RouteResearchError):
            MODULE.decide(counter)

    def test_terminal_states_cannot_transition_and_replay_is_deterministic(self) -> None:
        document = read_fixture("luna-success.json")
        first = MODULE.decide(document)
        second = MODULE.decide(copy.deepcopy(document))
        self.assertEqual(first, second)
        self.assertEqual(MODULE.canonical_json(first), MODULE.canonical_json(second))

        terminal = copy.deepcopy(document)
        terminal["events"].append(precheck())
        with self.assertRaises(MODULE.RouteResearchError):
            MODULE.decide(terminal)

    def test_route_helper_reuses_p1_query(self) -> None:
        calls: list[str] = []
        original = MODULE.runtime_records.query_record

        def wrapped(*args: object, **kwargs: object) -> dict:
            calls.append("query")
            return original(*args, **kwargs)

        MODULE.runtime_records.query_record = wrapped
        try:
            MODULE.decide(read_fixture("luna-success.json"))
        finally:
            MODULE.runtime_records.query_record = original
        self.assertGreaterEqual(len(calls), 2)

    def test_cli_stdin_and_complementary_runtime_evidence(self) -> None:
        fixture_path = FIXTURE_ROOT / "luna-success.json"
        completed = subprocess.run(
            [sys.executable, str(HELPER), "decide", "-"],
            input=fixture_path.read_text(encoding="utf-8"),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["state"], MODULE.STATE_DONE_LUNA)
        self.assertNotIn("Traceback", completed.stderr)

        complementary = route_document(
            "cli-and-app-records.json",
            [precheck("fixture-cli-v2")],
        )
        rejected = subprocess.run(
            [sys.executable, str(HELPER), "decide", "-"],
            input=json.dumps(complementary),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(rejected.returncode, 0, rejected.stderr)
        self.assertEqual(json.loads(rejected.stdout)["state"], MODULE.STATE_STOP_UNVERIFIED)

        malformed = subprocess.run(
            [sys.executable, str(HELPER), "decide", "-"],
            input="{\"schema_version\": true}",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(malformed.returncode, 2)
        self.assertNotIn("Traceback", malformed.stderr)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
