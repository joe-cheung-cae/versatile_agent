#!/usr/bin/env python3
"""Validate and canonicalize one closed per-attempt runtime-route audit."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
ARTIFACT_KIND = "runtime_route_audit"
DOCUMENT_FIELDS = {"schema_version", "artifact_kind", "attempt"}
ATTEMPT_FIELDS = {
    "attempt_id",
    "task_packet_hash",
    "interface",
    "requested_agent_type",
    "requested_model",
    "requested_effort",
    "configured_agent_type",
    "configured_model",
    "configured_effort",
    "observed_agent_type",
    "observed_effective_model",
    "observed_effective_effort",
    "requested_sandbox",
    "observed_sandbox",
    "permission_profile",
    "status",
    "failure_class",
    "fallback_reason",
    "fallback_attempt",
    "evidence_source",
}
EVIDENCE_SOURCE_FIELDS = {
    "kind",
    "interface",
    "runtime_id",
    "attempt_id",
    "scope",
    "diagnostic_only",
}
SOURCE_KINDS = {
    "native_runtime_details",
    "app_task_details",
    "configured_agent_toml",
    "install_manifest",
    "diagnostic_probe",
}
SOURCE_SCOPES = {
    "single-attempt",
    "single-runtime",
    "configuration",
    "installation",
    "diagnostic-only",
    "unknown",
}
FAILURE_CLASSES = {
    "NONE",
    "NATIVE_ROUTING_FAILURE",
    "ROUTE_METADATA_MISSING",
    "ROUTE_METADATA_CONFLICT",
    "TASK_FAILURE",
    "TIMEOUT",
    "UNKNOWN_EXCEPTION",
}
STATUSES = {
    "task_success",
    "routing_failure",
    "content_failure",
    "tool_failure",
    "task_failure",
    "timeout",
    "unknown_exception",
    "LUNA_PENDING",
    "TERRA_PENDING",
    "DONE_LUNA",
    "DONE_TERRA",
    "FALLBACK_PENDING",
    "STOP_FAILED",
    "STOP_UNVERIFIED",
}
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
UNKNOWN = "unknown"


class RuntimeAuditError(ValueError):
    """Raised for malformed, mixed, or unsafe audit evidence."""


def _reject_constant(value: str) -> None:
    raise RuntimeAuditError(f"non-finite JSON number is not allowed: {value}")


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeAuditError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _reject_surrogates(value: Any, location: str = "document") -> None:
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise RuntimeAuditError(f"{location} contains an unpaired surrogate")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_surrogates(key, f"{location}.<key>")
            _reject_surrogates(item, f"{location}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_surrogates(item, f"{location}[{index}]")


def _require_string(value: Any, location: str, *, allow_unknown: bool = True) -> str:
    if not isinstance(value, str):
        raise RuntimeAuditError(f"{location} must be a string")
    if not value or value != value.strip() or any(ord(character) < 0x20 for character in value):
        raise RuntimeAuditError(f"{location} must be a non-empty, unpadded string")
    if not allow_unknown and value == UNKNOWN:
        raise RuntimeAuditError(f"{location} must be known")
    return value


def _validate_atomic_tuple(attempt: dict[str, Any], fields: tuple[str, ...], location: str) -> None:
    values = [_require_string(attempt[field], f"{location}.{field}") for field in fields]
    known = [value != UNKNOWN for value in values]
    if any(known) and not all(known):
        raise RuntimeAuditError(f"{location} must be all known or all unknown")


def _is_native_interface(value: str) -> bool:
    return value == "native" or value.startswith("native") or value.startswith("codex_native")


def _validate_evidence_source(value: Any, attempt: dict[str, Any]) -> None:
    location = "attempt.evidence_source"
    if not isinstance(value, dict):
        raise RuntimeAuditError(f"{location} must be an object")
    extra = set(value) - EVIDENCE_SOURCE_FIELDS
    missing = EVIDENCE_SOURCE_FIELDS - set(value)
    if extra:
        raise RuntimeAuditError(f"{location} has unsupported fields: {sorted(extra)}")
    if missing:
        raise RuntimeAuditError(f"{location} is missing required fields: {sorted(missing)}")

    kind = _require_string(value["kind"], f"{location}.kind", allow_unknown=False)
    if kind not in SOURCE_KINDS:
        raise RuntimeAuditError(f"{location}.kind is unsupported: {kind}")
    interface = _require_string(value["interface"], f"{location}.interface")
    runtime_id = _require_string(value["runtime_id"], f"{location}.runtime_id")
    source_attempt_id = _require_string(value["attempt_id"], f"{location}.attempt_id")
    scope = _require_string(value["scope"], f"{location}.scope")
    if scope not in SOURCE_SCOPES:
        raise RuntimeAuditError(f"{location}.scope is unsupported: {scope}")
    if not isinstance(value["diagnostic_only"], bool):
        raise RuntimeAuditError(f"{location}.diagnostic_only must be boolean")
    if value["diagnostic_only"] != (kind == "diagnostic_probe"):
        raise RuntimeAuditError(f"{location}.diagnostic_only conflicts with source kind")

    if interface != UNKNOWN and attempt["interface"] != UNKNOWN and interface != attempt["interface"]:
        raise RuntimeAuditError(f"{location}.interface must match attempt.interface")

    observed_fields = (
        "observed_agent_type",
        "observed_effective_model",
        "observed_effective_effort",
    )
    observed_known = all(attempt[field] != UNKNOWN for field in observed_fields)
    if not observed_known:
        return

    if kind != "native_runtime_details":
        raise RuntimeAuditError(
            "known observed effective facts require native_runtime_details evidence; "
            "configuration, installation, diagnostic, and App-task evidence cannot fill them"
        )
    if scope != "single-attempt":
        raise RuntimeAuditError("known observed effective facts require single-attempt evidence")
    if value["diagnostic_only"] is not False:
        raise RuntimeAuditError("native effective evidence must not be diagnostic_only")
    if not _is_native_interface(interface) or not _is_native_interface(attempt["interface"]):
        raise RuntimeAuditError("known observed effective facts require native interfaces")
    if source_attempt_id != attempt["attempt_id"]:
        raise RuntimeAuditError("native evidence attempt_id must match the audited attempt")
    if runtime_id == UNKNOWN:
        raise RuntimeAuditError("known observed effective facts require a known runtime_id")


def validate_document(document: Any) -> dict[str, Any]:
    """Validate one closed runtime-route audit without adding or inferring facts."""

    if not isinstance(document, dict):
        raise RuntimeAuditError("document must be an object")
    extra = set(document) - DOCUMENT_FIELDS
    missing = DOCUMENT_FIELDS - set(document)
    if extra:
        raise RuntimeAuditError(f"document has unsupported fields: {sorted(extra)}")
    if missing:
        raise RuntimeAuditError(f"document is missing required fields: {sorted(missing)}")
    if document["artifact_kind"] != ARTIFACT_KIND:
        raise RuntimeAuditError(f"document.artifact_kind must be {ARTIFACT_KIND}")
    if type(document["schema_version"]) is not int or document["schema_version"] != SCHEMA_VERSION:
        raise RuntimeAuditError(f"document.schema_version must be {SCHEMA_VERSION}")

    attempt = document["attempt"]
    if not isinstance(attempt, dict):
        raise RuntimeAuditError("document.attempt must be an object")
    extra_attempt = set(attempt) - ATTEMPT_FIELDS
    missing_attempt = ATTEMPT_FIELDS - set(attempt)
    if extra_attempt:
        raise RuntimeAuditError(f"document.attempt has unsupported fields: {sorted(extra_attempt)}")
    if missing_attempt:
        raise RuntimeAuditError(f"document.attempt is missing required fields: {sorted(missing_attempt)}")

    _require_string(attempt["attempt_id"], "attempt.attempt_id", allow_unknown=False)
    task_packet_hash = _require_string(attempt["task_packet_hash"], "attempt.task_packet_hash", allow_unknown=False)
    if not _HASH_RE.fullmatch(task_packet_hash):
        raise RuntimeAuditError("attempt.task_packet_hash must be sha256:<64 lowercase hex digits>")
    _require_string(attempt["interface"], "attempt.interface")
    _validate_atomic_tuple(
        attempt,
        ("requested_agent_type", "requested_model", "requested_effort"),
        "attempt.requested",
    )
    _validate_atomic_tuple(
        attempt,
        ("configured_agent_type", "configured_model", "configured_effort"),
        "attempt.configured",
    )
    _validate_atomic_tuple(
        attempt,
        ("observed_agent_type", "observed_effective_model", "observed_effective_effort"),
        "attempt.observed_effective",
    )
    for field in ("requested_sandbox", "observed_sandbox", "permission_profile", "fallback_reason"):
        _require_string(attempt[field], f"attempt.{field}")
    status = _require_string(attempt["status"], "attempt.status", allow_unknown=False)
    if status not in STATUSES:
        raise RuntimeAuditError(f"attempt.status is unsupported: {status}")
    failure_class = _require_string(attempt["failure_class"], "attempt.failure_class", allow_unknown=False)
    if failure_class not in FAILURE_CLASSES:
        raise RuntimeAuditError(f"attempt.failure_class is unsupported: {failure_class}")
    if type(attempt["fallback_attempt"]) is not int or attempt["fallback_attempt"] not in {0, 1}:
        raise RuntimeAuditError("attempt.fallback_attempt must be integer 0 or 1")
    _validate_evidence_source(attempt["evidence_source"], attempt)
    _reject_surrogates(document)
    return document


def canonical_json(document: Any) -> str:
    """Return deterministic JSON while preserving every caller-supplied fact."""

    validate_document(document)
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def load_document(path: str | Path) -> dict[str, Any]:
    """Load one audit with strict UTF-8 and duplicate-member rejection."""

    try:
        source = sys.stdin.buffer.read().decode("utf-8") if str(path) == "-" else Path(path).read_bytes().decode("utf-8")
        document = json.loads(
            source,
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeAuditError(f"invalid UTF-8 JSON: {exc}") from exc
    return validate_document(document)


def write_document(path: str | Path, document: dict[str, Any]) -> None:
    """Atomically replace ``path`` with canonical audit JSON."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_json(document).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, destination)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate or canonicalize one runtime-route audit.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate an audit; use - for stdin")
    validate.add_argument("input", nargs="?", default="-")
    canonicalize = subparsers.add_parser("canonicalize", help="canonicalize an audit; use - for stdin")
    canonicalize.add_argument("input", nargs="?", default="-")
    canonicalize.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        document = load_document(args.input)
        if args.command == "validate":
            print("valid runtime-route-audit document")
        elif args.output is None:
            sys.stdout.write(canonical_json(document))
        else:
            write_document(args.output, document)
        return 0
    except (OSError, RuntimeAuditError) as exc:
        print(f"runtime-audit error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
