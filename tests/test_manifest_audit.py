#!/usr/bin/env python3
"""Focused offline coverage for P1-3 artifact separation and audit validation."""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_HELPER = ROOT / "scripts/write_manifest.py"
AUDIT_HELPER = ROOT / "payload/skills/versatile-dev/scripts/runtime_audit.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


manifest = load_module("write_manifest_p13", MANIFEST_HELPER)
audit = load_module("runtime_audit_p13", AUDIT_HELPER)


def valid_attempt(**overrides: object) -> dict[str, object]:
    attempt: dict[str, object] = {
        "attempt_id": "attempt-1",
        "task_packet_hash": "sha256:" + "a" * 64,
        "interface": "native_spawn",
        "requested_agent_type": "docs_researcher_luna",
        "requested_model": "gpt-5.6-luna",
        "requested_effort": "max",
        "configured_agent_type": "docs_researcher_luna",
        "configured_model": "gpt-5.6-luna",
        "configured_effort": "max",
        "observed_agent_type": "docs_researcher_luna",
        "observed_effective_model": "gpt-5.6-luna",
        "observed_effective_effort": "max",
        "requested_sandbox": "read-only",
        "observed_sandbox": "read-only",
        "permission_profile": "read-only",
        "status": "task_success",
        "failure_class": "NONE",
        "fallback_reason": "unknown",
        "fallback_attempt": 0,
        "evidence_source": {
            "kind": "native_runtime_details",
            "interface": "native_spawn",
            "runtime_id": "native-runtime-1",
            "attempt_id": "attempt-1",
            "scope": "single-attempt",
            "diagnostic_only": False,
        },
    }
    attempt.update(overrides)
    return attempt


def valid_document(**overrides: object) -> dict[str, object]:
    attempt = valid_attempt(**overrides)
    return {
        "schema_version": audit.SCHEMA_VERSION,
        "artifact_kind": audit.ARTIFACT_KIND,
        "attempt": attempt,
    }


class ManifestTests(unittest.TestCase):
    def test_manifest_is_closed_v2_configuration_document(self) -> None:
        document = manifest.build_manifest("luna-v1", "project", "2.0.0")
        self.assertEqual(
            set(document),
            {
                "artifact_kind",
                "schema_version",
                "bundle_version",
                "installed_at",
                "scope",
                "selected_profile",
                "installed_agents",
                "configured_researchers",
            },
        )
        self.assertEqual(document["artifact_kind"], "installation_manifest")
        self.assertEqual(document["schema_version"], 2)
        self.assertEqual(len(document["installed_agents"]), 13)
        self.assertEqual(set(document["installed_agents"]), set(manifest.INSTALLED_AGENT_TYPES))
        self.assertEqual(document["configured_researchers"], manifest.CONFIGURED_RESEARCHERS)
        serialized = json.dumps(document)
        for forbidden in ("runtime_probe", "observed", "effective", "fallback_success", "capability"):
            self.assertNotIn(forbidden, serialized)

    def test_manifest_configuration_facts_ignore_installed_at_only(self) -> None:
        document = manifest.build_manifest("terra-fallback", "user", "2.0.0")
        changed = copy.deepcopy(document)
        changed["installed_at"] = "2030-01-01T00:00:00+00:00"
        self.assertEqual(manifest.configuration_facts(document), manifest.configuration_facts(changed))

        changed["runtime_probe"] = {}
        with self.assertRaises(manifest.ManifestError):
            manifest.validate_manifest(changed)

    def test_manifest_rejects_duplicate_and_invalid_utf8_without_permissive_decode(self) -> None:
        duplicate = b'{"artifact_kind":"installation_manifest","artifact_kind":"installation_manifest"}'
        invalid = b"{\xff"
        with tempfile.TemporaryDirectory() as directory:
            duplicate_path = Path(directory) / "duplicate.json"
            invalid_path = Path(directory) / "invalid.json"
            duplicate_path.write_bytes(duplicate)
            invalid_path.write_bytes(invalid)
            for path in (duplicate_path, invalid_path):
                with self.subTest(path=path):
                    with self.assertRaises(manifest.ManifestError):
                        manifest.load_manifest(path)

    def test_manifest_writer_removed_probe_argument(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    str(MANIFEST_HELPER),
                    "--output",
                    str(Path(directory) / "manifest.json"),
                    "--profile",
                    "luna-v1",
                    "--scope",
                    "project",
                    "--source-version",
                    "2.0.0",
                    "--probe",
                    str(Path(directory) / "probe.json"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)


class RuntimeAuditTests(unittest.TestCase):
    def test_unknown_values_round_trip_without_inference(self) -> None:
        document = valid_document(
            requested_agent_type="unknown",
            requested_model="unknown",
            requested_effort="unknown",
            configured_agent_type="unknown",
            configured_model="unknown",
            configured_effort="unknown",
            observed_agent_type="unknown",
            observed_effective_model="unknown",
            observed_effective_effort="unknown",
            requested_sandbox="unknown",
            observed_sandbox="unknown",
            permission_profile="unknown",
            status="STOP_UNVERIFIED",
            failure_class="ROUTE_METADATA_MISSING",
            evidence_source={
                "kind": "diagnostic_probe",
                "interface": "native_spawn",
                "runtime_id": "probe-runtime-1",
                "attempt_id": "attempt-1",
                "scope": "diagnostic-only",
                "diagnostic_only": True,
            },
        )
        canonical = audit.canonical_json(document)
        restored = json.loads(canonical)
        self.assertEqual(restored, document)
        self.assertEqual(restored["attempt"]["observed_effective_model"], "unknown")
        self.assertEqual(restored["attempt"]["configured_model"], "unknown")

    def test_native_effective_tuple_requires_native_same_attempt_evidence(self) -> None:
        document = valid_document()
        audit.validate_document(document)
        for kind in ("app_task_details", "diagnostic_probe", "configured_agent_toml", "install_manifest"):
            mixed = copy.deepcopy(document)
            mixed["attempt"]["evidence_source"] = {
                "kind": kind,
                "interface": "native_spawn",
                "runtime_id": "source-1",
                "attempt_id": "attempt-1",
                "scope": "single-attempt" if kind == "app_task_details" else "configuration",
                "diagnostic_only": kind == "diagnostic_probe",
            }
            with self.subTest(kind=kind), self.assertRaises(audit.RuntimeAuditError):
                audit.validate_document(mixed)

        for field in ("scope", "attempt_id", "interface"):
            mismatch = copy.deepcopy(document)
            if field == "scope":
                mismatch["attempt"]["evidence_source"][field] = "single-runtime"
            elif field == "attempt_id":
                mismatch["attempt"]["evidence_source"][field] = "attempt-2"
            else:
                mismatch["attempt"]["evidence_source"][field] = "app_task"
            with self.subTest(field=field), self.assertRaises(audit.RuntimeAuditError):
                audit.validate_document(mismatch)

    def test_native_interface_classification_is_closed_for_attempt_and_evidence(self) -> None:
        invalid_interfaces = (
            "native_app_task",
            "native_app_task_details",
            "nativeish",
            "codex_native_app_task",
            "codex_native_fake",
            "native_spawn_extra",
            "native_spawn_attemptish",
            "xnative_spawn",
        )
        with tempfile.TemporaryDirectory() as directory:
            for invalid_interface in invalid_interfaces:
                document = valid_document()
                document["attempt"]["interface"] = invalid_interface
                document["attempt"]["evidence_source"]["interface"] = invalid_interface
                with self.subTest(interface=invalid_interface):
                    with self.assertRaises(audit.RuntimeAuditError):
                        audit.validate_document(document)

                    source = Path(directory) / f"{invalid_interface}.json"
                    source.write_text(json.dumps(document), encoding="utf-8")
                    result = subprocess.run(
                        [sys.executable, str(AUDIT_HELPER), "validate", str(source)],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertNotIn("Traceback", result.stderr)

    def test_requested_configured_and_observed_tuples_are_atomic(self) -> None:
        for fields in (
            ("requested_agent_type", "requested_model", "requested_effort"),
            ("configured_agent_type", "configured_model", "configured_effort"),
            ("observed_agent_type", "observed_effective_model", "observed_effective_effort"),
        ):
            partial = valid_document()
            for field in fields[1:]:
                partial["attempt"][field] = "unknown"
            with self.subTest(fields=fields), self.assertRaises(audit.RuntimeAuditError):
                audit.validate_document(partial)

    def test_audit_is_not_an_installation_manifest_and_rejects_extra_fields(self) -> None:
        document = valid_document()
        document["runtime_probe"] = {}
        with self.assertRaises(audit.RuntimeAuditError):
            audit.validate_document(document)
        with self.assertRaises(audit.RuntimeAuditError):
            audit.validate_document(manifest.build_manifest("luna-v1", "project", "2.0.0"))

    def test_duplicate_utf8_and_cli_errors_are_controlled(self) -> None:
        duplicate = b'{"schema_version":1,"artifact_kind":"runtime_route_audit","attempt":{},"attempt":{"x":1}}'
        invalid = b"{\xff"
        with tempfile.TemporaryDirectory() as directory:
            duplicate_path = Path(directory) / "duplicate.json"
            invalid_path = Path(directory) / "invalid.json"
            duplicate_path.write_bytes(duplicate)
            invalid_path.write_bytes(invalid)
            for path in (duplicate_path, invalid_path):
                with self.subTest(direct_load=path):
                    with self.assertRaises(audit.RuntimeAuditError):
                        audit.load_document(path)
                result = subprocess.run(
                    [sys.executable, str(AUDIT_HELPER), "validate", str(path)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                with self.subTest(path=path):
                    self.assertEqual(result.returncode, 2)
                    self.assertNotIn("Traceback", result.stderr)

    def test_valid_native_audit_canonicalizes_to_a_separate_atomic_file(self) -> None:
        document = valid_document()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.json"
            output = Path(directory) / "audit.json"
            source.write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(AUDIT_HELPER), "canonicalize", str(source), "--output", str(output)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_text(encoding="utf-8"), audit.canonical_json(document))
            self.assertFalse(any(path.name.startswith(".audit.json.") for path in Path(directory).iterdir()))

    def test_fallback_hash_and_padded_values_are_validated_without_cross_file_inference(self) -> None:
        bad_hash = valid_document()
        bad_hash["attempt"]["task_packet_hash"] = "sha256:" + "A" * 64
        with self.assertRaises(audit.RuntimeAuditError):
            audit.validate_document(bad_hash)

        bad_counter = valid_document(fallback_attempt="1")
        with self.assertRaises(audit.RuntimeAuditError):
            audit.validate_document(bad_counter)

        padded = valid_document(requested_model=" gpt-5.6-luna")
        with self.assertRaises(audit.RuntimeAuditError):
            audit.validate_document(padded)


if __name__ == "__main__":
    unittest.main()
