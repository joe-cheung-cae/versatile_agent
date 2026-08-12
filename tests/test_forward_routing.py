#!/usr/bin/env python3
"""Offline behavioral coverage for the Skill forward planner."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tomllib
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
FORWARD_HELPER = ROOT / "payload/skills/versatile-dev/scripts/forward_router.py"
ROUTE_HELPER = ROOT / "payload/skills/versatile-dev/scripts/route_research.py"
TASK_FIXTURE = ROOT / "tests/fixtures/forward/tasks.json"
LIVE_ENTRYPOINT = ROOT / "tests/test_live_codex.sh"


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
        route_document = json.loads(
            (ROOT / "tests/fixtures/routing/luna-mismatch.json").read_text(encoding="utf-8")
        )
        fallback_state = ROUTE.decide(route_document)
        plan = FORWARD.forward_route(packet, fallback_state)
        self.assertEqual(fallback_state["state"], ROUTE.STATE_FALLBACK_PENDING)
        self.assertEqual(plan["selected_agents"], ["docs_researcher_terra"])
        self.assertEqual(plan["next_action"], "spawn_terra")
        self.assertEqual(plan["fallback_attempt"], 1)
        self.assertEqual(plan["handoff"]["fallback_attempt"], 1)
        self.assertEqual(plan["handoff"]["task_packet_hash"], packet["task_packet_hash"])
        self.assertEqual(plan["handoff"]["requested_route"], {"route": "terra", **ROUTE.ROUTES["terra"]})

    def test_terminal_route_failures_never_create_a_terra_handoff(self) -> None:
        base = json.loads(
            (ROOT / "tests/fixtures/routing/luna-success.json").read_text(encoding="utf-8")
        )
        packet = copy.deepcopy(CASES["docs"])
        packet["task_packet_hash"] = base["task_packet_hash"]
        statuses = (
            ("content_failure", "TASK_FAILURE"),
            ("tool_failure", "TASK_FAILURE"),
            ("task_failure", "TASK_FAILURE"),
            ("timeout", "TIMEOUT"),
            ("unknown_exception", "UNKNOWN_EXCEPTION"),
        )
        for status, failure_class in statuses:
            with self.subTest(status=status):
                document = copy.deepcopy(base)
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
                plan = FORWARD.forward_route(packet, route_state)
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
            [["implementer", "tester"], ["performance_profiler"]],
        )
        self.assertNotEqual(plan["writer_batches"][0], plan["writer_batches"][1])

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

    def test_route_handoff_rejects_changed_packet_hash(self) -> None:
        route_document = json.loads(
            (ROOT / "tests/fixtures/routing/luna-mismatch.json").read_text(encoding="utf-8")
        )
        route_state = ROUTE.decide(route_document)
        packet = copy.deepcopy(CASES["docs"])
        packet["task_packet_hash"] = "sha256:9999999999999999999999999999999999999999999999999999999999999999"
        with self.assertRaises(FORWARD.ForwardRouteError):
            FORWARD.forward_route(packet, route_state)

    def test_route_handoff_requires_classified_failure_and_exact_fallback_count(self) -> None:
        route_document = json.loads(
            (ROOT / "tests/fixtures/routing/luna-mismatch.json").read_text(encoding="utf-8")
        )
        route_state = ROUTE.decide(route_document)
        for mutation in (
            lambda state: state.update({"failure_class": "TASK_FAILURE"}),
            lambda state: state.update({"fallback_attempt": 0}),
        ):
            with self.subTest(mutation=mutation):
                invalid_state = copy.deepcopy(route_state)
                mutation(invalid_state)
                with self.assertRaises(FORWARD.ForwardRouteError):
                    FORWARD.forward_route(CASES["docs"], invalid_state)

    def test_offline_gate_excludes_optional_live_entrypoint_exactly(self) -> None:
        run_script = (ROOT / "tests/run.sh").read_text(encoding="utf-8")
        package_script = (ROOT / "package.sh").read_text(encoding="utf-8")
        self.assertIn("test_forward_routing.py", run_script)
        self.assertNotIn("test_live_codex.sh", run_script)
        self.assertNotIn("RUN_CODEX_LIVE", run_script)
        self.assertNotIn("test_live_codex.sh", package_script)
        self.assertNotIn("RUN_CODEX_LIVE", package_script)
        self.assertTrue(LIVE_ENTRYPOINT.exists())


if __name__ == "__main__":
    raise SystemExit(unittest.main())
