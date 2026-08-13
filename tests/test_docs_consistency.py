#!/usr/bin/env python3
"""Offline checks that public documentation follows shipped source facts."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
import tomllib
import unittest
from pathlib import Path


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
DEVELOPMENT_PLAN = ROOT / "DEVELOPMENT_PLAN.md"
AGENT_ROOT = ROOT / "payload/agents/common"
FORWARD_HELPER = ROOT / "payload/skills/versatile-dev/scripts/forward_router.py"
ROUTE_HELPER = ROOT / "payload/skills/versatile-dev/scripts/route_research.py"
AUDIT_HELPER = ROOT / "payload/skills/versatile-dev/scripts/runtime_audit.py"
MANIFEST_HELPER = ROOT / "scripts/write_manifest.py"
FORWARD_FIXTURE = ROOT / "tests/fixtures/forward/tasks.json"
ROUTE_FIXTURE_ROOT = ROOT / "tests/fixtures/routing"
LIVE_ENTRYPOINT = ROOT / "tests/test_live_codex.sh"
LIVE_FIXTURE = ROOT / "tests/fixtures/live/native-luna-schema-sample.json"
RUN_SCRIPT = ROOT / "tests/run.sh"
PACKAGE_SCRIPT = ROOT / "package.sh"
VERSION_FILE = ROOT / "VERSION"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Keep the real module names so forward_router imports the same route helper
# that the tests use.  All inputs below are local fixtures; no network or auth
# path is available to this test.
ROUTE = load_module("route_research", ROUTE_HELPER)
FORWARD = load_module("forward_router", FORWARD_HELPER)
AUDIT = load_module("runtime_audit_docs_consistency", AUDIT_HELPER)
MANIFEST = load_module("write_manifest_docs_consistency", MANIFEST_HELPER)


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def bind_route_document(document: dict[str, object], task_packet_hash: str) -> dict[str, object]:
    bound = copy.deepcopy(document)
    bound["task_packet_hash"] = task_packet_hash
    for event in bound["events"]:  # type: ignore[index]
        event["task_packet_hash"] = task_packet_hash
    return bound


def run_live(enabled: bool) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("RUN_CODEX_LIVE", None)
    environment.pop("CODEX_LIVE_EVIDENCE_FILE", None)
    if enabled:
        environment.update(
            {
                "RUN_CODEX_LIVE": "1",
                "CODEX_LIVE_EVIDENCE_FILE": str(LIVE_FIXTURE),
            }
        )
    else:
        environment["RUN_CODEX_LIVE"] = "0"
    return subprocess.run(
        ["bash", str(LIVE_ENTRYPOINT)],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


class DocumentationConsistencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.readme = README.read_text(encoding="utf-8")
        cls.plan = DEVELOPMENT_PLAN.read_text(encoding="utf-8")
        cls.docs = f"{cls.readme}\n{cls.plan}"

    def test_manifest_and_agent_facts_are_derived_from_shipped_sources(self) -> None:
        manifest = MANIFEST.build_manifest("luna-v1", "project", "0.1.0")
        agent_paths = sorted(AGENT_ROOT.glob("*.toml"))
        agent_documents = {
            document["name"]: document
            for document in (
                tomllib.loads(path.read_text(encoding="utf-8")) for path in agent_paths
            )
        }

        self.assertEqual(len(agent_paths), len(MANIFEST.INSTALLED_AGENT_TYPES))
        self.assertEqual(set(agent_documents), set(manifest["installed_agents"]))
        self.assertEqual(len(agent_documents), len(set(agent_documents)))
        self.assertEqual(len(agent_documents), 13)
        for agent_name in manifest["installed_agents"]:
            self.assertIn(agent_name, self.docs)

        for agent_name, configured in manifest["configured_researchers"].items():
            source = agent_documents[agent_name]
            self.assertEqual(source["name"], configured["agent_type"])
            self.assertEqual(source["model"], configured["model"])
            self.assertEqual(source["model_reasoning_effort"], configured["effort"])
            for value in (configured["agent_type"], configured["model"], configured["effort"]):
                self.assertIn(value, self.docs)

        for field in MANIFEST.MANIFEST_FIELDS:
            self.assertIn(field, self.docs)
        self.assertIn(f"artifact_kind={MANIFEST.ARTIFACT_KIND}", self.plan)
        self.assertIn(f"schema_version={MANIFEST.SCHEMA_VERSION}", self.plan)

        mutated = copy.deepcopy(manifest)
        mutated["installed_agents"][0] = "not-a-shipped-agent"  # type: ignore[index]
        with self.assertRaises(MANIFEST.ManifestError):
            MANIFEST.validate_manifest(mutated)

    def test_route_fixtures_derive_parent_state_and_terminal_behavior(self) -> None:
        successful_luna = load_json(ROUTE_FIXTURE_ROOT / "luna-success.json")
        luna_mismatch = load_json(ROUTE_FIXTURE_ROOT / "luna-mismatch.json")
        routing_rejection = load_json(ROUTE_FIXTURE_ROOT / "luna-routing-rejection.json")
        successful_terra = load_json(ROUTE_FIXTURE_ROOT / "terra-success.json")

        luna_state = ROUTE.decide(successful_luna)
        fallback_state = ROUTE.decide(luna_mismatch)
        rejection_state = ROUTE.decide(routing_rejection)
        terra_state = ROUTE.decide(successful_terra)

        self.assertEqual(luna_state["state"], ROUTE.STATE_DONE_LUNA)
        self.assertEqual(luna_state["next_action"], "none")
        self.assertTrue(luna_state["terminal"])
        self.assertEqual(fallback_state["state"], ROUTE.STATE_FALLBACK_PENDING)
        self.assertEqual(fallback_state["next_action"], "spawn_terra")
        self.assertEqual(fallback_state["failure_class"], "NATIVE_ROUTING_FAILURE")
        self.assertEqual(fallback_state["fallback_attempt"], 1)
        self.assertFalse(fallback_state["terminal"])
        self.assertEqual(rejection_state["state"], ROUTE.STATE_FALLBACK_PENDING)
        self.assertEqual(rejection_state["next_action"], "spawn_terra")
        self.assertEqual(
            rejection_state["failure_class"],
            ROUTE._failure_class_for_status(routing_rejection["events"][1]["status"]),  # type: ignore[index]
        )
        self.assertEqual(rejection_state["fallback_attempt"], 1)
        self.assertFalse(rejection_state["terminal"])
        self.assertEqual(terra_state["state"], ROUTE.STATE_DONE_TERRA)
        self.assertEqual(terra_state["next_action"], "none")
        self.assertTrue(terra_state["terminal"])

        for route in ROUTE.ROUTES.values():
            for value in route.values():
                self.assertIn(value, self.docs)
        for state in (
            ROUTE.STATE_FALLBACK_PENDING,
            ROUTE.STATE_DONE_LUNA,
            ROUTE.STATE_DONE_TERRA,
            ROUTE.STATE_STOP_FAILED,
            ROUTE.STATE_STOP_UNVERIFIED,
        ):
            self.assertIn(state, self.docs)
        for action in ("spawn_luna", "spawn_terra", "none"):
            self.assertIn(action, self.docs)
        rejection_event = routing_rejection["events"][1]  # type: ignore[index]
        for token in (
            "explicit same-attempt native routing rejection",
            rejection_event["routing_failure"],  # type: ignore[index]
            rejection_state["state"],
            rejection_state["failure_class"],
            f"fallback_attempt={rejection_state['fallback_attempt']}",
            f"next_action={rejection_state['next_action']}",
        ):
            self.assertIn(token, self.plan)

        mutated = copy.deepcopy(successful_luna)
        mutated["events"][1].update(  # type: ignore[index]
            {
                "status": "content_failure",
                "failure_class": ROUTE._failure_class_for_status("content_failure"),
            }
        )
        mutated_state = ROUTE.decide(mutated)
        self.assertNotEqual(mutated_state["state"], luna_state["state"])
        self.assertEqual(mutated_state["state"], ROUTE.STATE_STOP_FAILED)
        self.assertEqual(mutated_state["next_action"], "none")
        self.assertEqual(mutated_state["failure_class"], "TASK_FAILURE")
        self.assertEqual(mutated_state["fallback_attempt"], 0)
        self.assertTrue(mutated_state["terminal"])

        timeout = copy.deepcopy(successful_luna)
        timeout["events"][1].update(  # type: ignore[index]
            {
                "status": "timeout",
                "failure_class": ROUTE._failure_class_for_status("timeout"),
            }
        )
        timeout_state = ROUTE.decide(timeout)
        self.assertEqual(timeout_state["state"], ROUTE.STATE_STOP_FAILED)
        self.assertEqual(timeout_state["next_action"], "none")
        self.assertEqual(timeout_state["failure_class"], "TIMEOUT")
        self.assertEqual(timeout_state["fallback_attempt"], 0)
        self.assertTrue(timeout_state["terminal"])

        unknown_exception = copy.deepcopy(successful_luna)
        unknown_exception["events"][1].update(  # type: ignore[index]
            {
                "status": "unknown_exception",
                "failure_class": ROUTE._failure_class_for_status("unknown_exception"),
            }
        )
        unknown_state = ROUTE.decide(unknown_exception)
        self.assertEqual(unknown_state["state"], ROUTE.STATE_STOP_UNVERIFIED)
        self.assertEqual(unknown_state["next_action"], "none")
        self.assertEqual(unknown_state["failure_class"], "UNKNOWN_EXCEPTION")
        self.assertEqual(unknown_state["fallback_attempt"], 0)
        self.assertTrue(unknown_state["terminal"])
        for state in (timeout_state, unknown_state):
            self.assertNotEqual(state["next_action"], "spawn_terra")
        for token in (
            timeout_state["state"],
            timeout_state["failure_class"],
            unknown_state["state"],
            unknown_state["failure_class"],
            "complete, non-conflicting effective route metadata",
            "never authorizes Terra",
        ):
            self.assertIn(token, self.plan)

    def test_forward_plan_and_app_authorization_are_derived_and_non_noop(self) -> None:
        cases = load_json(FORWARD_FIXTURE)["cases"]  # type: ignore[index]
        docs_packet = cases["docs"]  # type: ignore[index]
        docs_plan = FORWARD.plan_forward(docs_packet)
        policy = docs_plan["fallback_policy"]

        self.assertEqual(
            docs_plan["selected_agents"],
            [ROUTE.ROUTES["luna"]["agent_type"]],
        )
        self.assertEqual(docs_plan["next_action"], "precheck")
        self.assertEqual(docs_plan["requested_route"], {"route": "luna", **ROUTE.ROUTES["luna"]})
        self.assertEqual(policy["permitted_failure_class"], "NATIVE_ROUTING_FAILURE")
        self.assertEqual(policy["max_attempts"], 1)
        self.assertTrue(policy["same_task_packet_hash"])
        for token in (
            "next_action=precheck",
            f"permitted_failure_class={policy['permitted_failure_class']}",
            f"max_attempts={policy['max_attempts']}",
            "same_task_packet_hash=true",
        ):
            self.assertIn(token, self.plan)

        bound_mismatch = bind_route_document(
            load_json(ROUTE_FIXTURE_ROOT / "luna-mismatch.json"),
            docs_packet["task_packet_hash"],  # type: ignore[index]
        )
        fallback_plan = FORWARD.forward_route(docs_packet, bound_mismatch)
        self.assertEqual(fallback_plan["route_state"], ROUTE.STATE_FALLBACK_PENDING)
        self.assertEqual(fallback_plan["next_action"], "spawn_terra")
        self.assertEqual(
            fallback_plan["selected_agents"],
            [ROUTE.ROUTES["terra"]["agent_type"]],
        )
        self.assertEqual(fallback_plan["handoff"]["fallback_attempt"], 1)  # type: ignore[index]
        self.assertEqual(
            fallback_plan["handoff"]["task_packet_hash"],  # type: ignore[index]
            docs_packet["task_packet_hash"],  # type: ignore[index]
        )

        no_app = FORWARD.plan_forward(cases["shared_writers"])  # type: ignore[index]
        unauthorized = FORWARD.plan_forward(cases["app_unauthorized"])  # type: ignore[index]
        authorized = FORWARD.plan_forward(cases["app_authorized"])  # type: ignore[index]
        self.assertFalse(no_app["app_task"]["requested"])
        self.assertFalse(no_app["app_task"]["allowed"])
        self.assertEqual(no_app["app_task"]["next_action"], "none")
        self.assertEqual(no_app["app_task"]["reason"], "no_app_task_requested")
        self.assertFalse(unauthorized["app_task"]["allowed"])
        self.assertTrue(unauthorized["app_task"]["requested"])
        self.assertEqual(unauthorized["app_task"]["next_action"], "stop_unverified")
        self.assertTrue(authorized["app_task"]["allowed"])
        self.assertTrue(authorized["app_task"]["requested"])
        self.assertEqual(authorized["app_task"]["next_action"], "create_app_task")
        self.assertNotEqual(unauthorized["app_task"], authorized["app_task"])
        for decision in (no_app["app_task"], authorized["app_task"], unauthorized["app_task"]):
            for token in (decision["next_action"], decision["reason"]):
                self.assertIn(token, self.plan)
        self.assertIn("three independent App-task outcomes", self.plan)

        mutated = copy.deepcopy(cases["app_unauthorized"])  # type: ignore[index]
        mutated["app_task"]["current_request_authorized"] = True  # type: ignore[index]
        mutated["task_packet_hash"] = FORWARD.canonical_packet_hash(mutated)
        mutated_plan = FORWARD.plan_forward(mutated)
        self.assertEqual(mutated_plan["app_task"]["next_action"], "create_app_task")
        self.assertNotEqual(mutated_plan["app_task"], unauthorized["app_task"])

    def test_runtime_audit_field_sets_and_sandbox_permission_terms_are_derived(self) -> None:
        live_sample = load_json(LIVE_FIXTURE)
        audit_document = live_sample["audit"]  # type: ignore[index]
        AUDIT.validate_document(audit_document)
        self.assertEqual(set(audit_document["attempt"]), AUDIT.ATTEMPT_FIELDS)  # type: ignore[index]
        self.assertEqual(set(AUDIT.DOCUMENT_FIELDS), {"schema_version", "artifact_kind", "attempt"})
        for field in AUDIT.ATTEMPT_FIELDS:
            self.assertIn(field, self.plan)
        for field in AUDIT.EVIDENCE_SOURCE_FIELDS:
            self.assertIn(field, self.plan)
        for field in ("requested_sandbox", "observed_sandbox", "permission_profile"):
            self.assertIn(f"`{field}`", self.plan)
        self.assertNotIn("requested_permission_profile", AUDIT.ATTEMPT_FIELDS)
        self.assertNotIn("requested_permission_profile", self.plan)

        mutated = copy.deepcopy(audit_document)
        del mutated["attempt"]["permission_profile"]  # type: ignore[index]
        with self.assertRaises(AUDIT.RuntimeAuditError):
            AUDIT.validate_document(mutated)

    def test_live_harness_and_package_contract_are_derived_from_scripts(self) -> None:
        disabled = run_live(False)
        self.assertEqual(disabled.returncode, 0)
        self.assertIn("SKIP:", disabled.stdout)

        enabled = run_live(True)
        enabled_output = enabled.stdout + enabled.stderr
        self.assertEqual(enabled.returncode, 2)
        self.assertIn("UNVERIFIED:", enabled_output)
        self.assertNotIn("CONFORMANCE VERIFIED", enabled_output)

        run_script = RUN_SCRIPT.read_text(encoding="utf-8")
        package = PACKAGE_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("test_docs_consistency.py", run_script)
        self.assertNotIn("test_live_codex.sh", run_script)
        self.assertNotIn("RUN_CODEX_LIVE", run_script)
        self.assertNotIn("test_live_codex.sh", package)
        self.assertNotIn("RUN_CODEX_LIVE", package)

        staged_blocks = re.findall(
            r'(?ms)cp -Rp \\\n+(.*?)\n\s*"\$staging_bundle/"',
            package,
        ) + re.findall(
            r'(?ms)cp -p \\\n+(.*?)\n\s*"\$staging_bundle/"',
            package,
        )
        staged_inputs = sorted(
            set(
                relative_path
                for block in staged_blocks
                for relative_path in re.findall(r'"\$bundle_root/([^"$]+)"', block)
            )
        )
        for relative_path in staged_inputs:
            label = f"`{relative_path}/`" if relative_path in {"payload", "scripts", "tests"} else f"`{relative_path}`"
            self.assertIn(label, self.plan)

        version = VERSION_FILE.read_text(encoding="utf-8").strip()
        bundle_match = re.search(r'bundle_name="([^"]*)\$version"', package)
        self.assertIsNotNone(bundle_match)
        bundle_prefix = bundle_match.group(1)  # type: ignore[union-attr]
        archive_name = f"{bundle_prefix}{version}.tar.gz"
        installer_name = f"{bundle_prefix}offline-installer-{version}.sh"
        self.assertIn(archive_name.replace(version, "<version>"), self.docs)
        self.assertIn(installer_name.replace(version, "<version>"), self.docs)
        self.assertIn('checksum_path="$output_dir/SHA256SUMS"', package)
        self.assertIn("SHA256SUMS", self.docs)

    def test_presentation_checks_remain_supplemental(self) -> None:
        license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", license_text)
        self.assertIn("Copyright (c) 2026 Joe Cheung", license_text)
        self.assertIn("Permission is hereby granted, free of charge", license_text)
        self.assertIn("MIT License", self.readme)

        for phrase in (
            "13 unique",
            "same canonical `task_packet_hash`",
            "schema-review harness only",
            "offline test gate",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.docs)
        for stale in (
            "twelve narrow custom agents",
            "12 narrow custom agents",
            "12 agents",
            "current installer selects one legacy `docs_researcher` profile",
            "future work",
            "selects Terra/High fallback",
            "Luna unavailable",
        ):
            with self.subTest(stale=stale):
                self.assertNotIn(stale.casefold(), self.docs.casefold())

    def test_mermaid_routes_helper_output_back_to_parent_before_dispatch(self) -> None:
        mermaid = self.plan.split("```mermaid", 1)[1].split("```", 1)[0]
        self.assertIn("R --> O", mermaid)
        self.assertIn("O -->|\"return replay/plan result\"| L", mermaid)
        self.assertIn("L -->|\"next_action=spawn_luna\"| LU", mermaid)
        self.assertIn("L -->|\"next_action=spawn_terra", mermaid)
        self.assertNotRegex(mermaid, r"R\s*-->.*\b(?:LU|TE)\b")


if __name__ == "__main__":
    raise SystemExit(unittest.main())
