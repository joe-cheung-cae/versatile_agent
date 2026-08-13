#!/usr/bin/env python3
"""Validate and atomically write the closed installation manifest."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 2
ARTIFACT_KIND = "installation_manifest"
MANIFEST_FIELDS = {
    "artifact_kind",
    "schema_version",
    "bundle_version",
    "installed_at",
    "scope",
    "selected_profile",
    "installed_agents",
    "configured_researchers",
}
LEGACY_PROFILES = {"luna-v1", "luna-v2", "terra-fallback"}
SCOPES = {"project", "user"}
INSTALLED_AGENT_TYPES = (
    "architect",
    "code_mapper",
    "docs_researcher_luna",
    "docs_researcher_terra",
    "gpu_reviewer",
    "implementer",
    "numerics_reviewer",
    "parallelism_reviewer",
    "performance_profiler",
    "reviewer",
    "security_reviewer",
    "test_validator",
    "tester",
)
CONFIGURED_RESEARCHERS = {
    "docs_researcher_luna": {
        "agent_type": "docs_researcher_luna",
        "model": "gpt-5.6-luna",
        "effort": "max",
    },
    "docs_researcher_terra": {
        "agent_type": "docs_researcher_terra",
        "model": "gpt-5.6-terra",
        "effort": "high",
    },
}


class ManifestError(ValueError):
    """Raised for malformed or semantically mixed manifest documents."""


def _reject_constant(value: str) -> None:
    raise ManifestError(f"non-finite JSON number is not allowed: {value}")


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError(f"duplicate JSON member: {key}")
        result[key] = value
    return result


def _reject_surrogates(value: Any, location: str = "document") -> None:
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ManifestError(f"{location} contains an unpaired surrogate")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_surrogates(key, f"{location}.<key>")
            _reject_surrogates(item, f"{location}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_surrogates(item, f"{location}[{index}]")


def _require_string(value: Any, location: str) -> str:
    if not isinstance(value, str):
        raise ManifestError(f"{location} must be a string")
    if not value or value != value.strip():
        raise ManifestError(f"{location} must be a non-empty, unpadded string")
    return value


def _validate_timestamp(value: Any) -> None:
    timestamp = _require_string(value, "document.installed_at")
    try:
        parsed = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManifestError("document.installed_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ManifestError("document.installed_at must include a timezone")


def _validate_researchers(value: Any) -> None:
    if not isinstance(value, dict):
        raise ManifestError("document.configured_researchers must be an object")
    if set(value) != set(CONFIGURED_RESEARCHERS):
        raise ManifestError(
            "document.configured_researchers must contain exactly the two configured researcher routes"
        )
    for agent_type, expected in CONFIGURED_RESEARCHERS.items():
        route = value[agent_type]
        if not isinstance(route, dict) or set(route) != {"agent_type", "model", "effort"}:
            raise ManifestError(f"document.configured_researchers.{agent_type} has unsupported fields")
        for field in ("agent_type", "model", "effort"):
            value_at_field = _require_string(route.get(field), f"document.configured_researchers.{agent_type}.{field}")
            if value_at_field != expected[field]:
                raise ManifestError(f"document.configured_researchers.{agent_type} has an unexpected {field}")


def validate_manifest(document: Any) -> dict[str, Any]:
    """Validate a schema-v2 installation manifest as a closed document."""

    if not isinstance(document, dict):
        raise ManifestError("document must be an object")
    extra = set(document) - MANIFEST_FIELDS
    missing = MANIFEST_FIELDS - set(document)
    if extra:
        raise ManifestError(f"document has unsupported fields: {sorted(extra)}")
    if missing:
        raise ManifestError(f"document is missing required fields: {sorted(missing)}")
    if document["artifact_kind"] != ARTIFACT_KIND:
        raise ManifestError(f"document.artifact_kind must be {ARTIFACT_KIND}")
    if type(document["schema_version"]) is not int or document["schema_version"] != SCHEMA_VERSION:
        raise ManifestError(f"document.schema_version must be {SCHEMA_VERSION}")
    _require_string(document["bundle_version"], "document.bundle_version")
    _validate_timestamp(document["installed_at"])
    scope = _require_string(document["scope"], "document.scope")
    if scope not in SCOPES:
        raise ManifestError(f"document.scope must be one of {sorted(SCOPES)}")
    profile = _require_string(document["selected_profile"], "document.selected_profile")
    if profile not in LEGACY_PROFILES:
        raise ManifestError(f"document.selected_profile must be one of {sorted(LEGACY_PROFILES)}")

    installed_agents = document["installed_agents"]
    if not isinstance(installed_agents, list):
        raise ManifestError("document.installed_agents must be a list")
    if len(installed_agents) != len(INSTALLED_AGENT_TYPES):
        raise ManifestError("document.installed_agents must contain exactly 13 identities")
    for index, agent_type in enumerate(installed_agents):
        _require_string(agent_type, f"document.installed_agents[{index}]")
    if len(set(installed_agents)) != len(installed_agents):
        raise ManifestError("document.installed_agents must not contain duplicates")
    if set(installed_agents) != set(INSTALLED_AGENT_TYPES):
        raise ManifestError("document.installed_agents does not match the installed bundle")
    _validate_researchers(document["configured_researchers"])
    _reject_surrogates(document)
    return document


def configuration_facts(document: Any) -> dict[str, Any]:
    """Return manifest facts used for idempotency, excluding ``installed_at``."""

    validated = validate_manifest(document)
    return {
        field: validated[field]
        for field in MANIFEST_FIELDS
        if field != "installed_at"
    }


def expected_configuration_facts(profile: str, scope: str, source_version: str) -> dict[str, Any]:
    """Build the immutable v2 facts expected for one installation."""

    profile = _require_string(profile, "profile")
    scope = _require_string(scope, "scope")
    source_version = _require_string(source_version, "source_version")
    if profile not in LEGACY_PROFILES:
        raise ManifestError(f"profile must be one of {sorted(LEGACY_PROFILES)}")
    if scope not in SCOPES:
        raise ManifestError(f"scope must be one of {sorted(SCOPES)}")
    return {
        "artifact_kind": ARTIFACT_KIND,
        "schema_version": SCHEMA_VERSION,
        "bundle_version": source_version,
        "scope": scope,
        "selected_profile": profile,
        "installed_agents": list(INSTALLED_AGENT_TYPES),
        "configured_researchers": json.loads(json.dumps(CONFIGURED_RESEARCHERS)),
    }


def build_manifest(profile: str, scope: str, source_version: str) -> dict[str, Any]:
    """Build a schema-v2 manifest containing configuration facts only."""

    document = expected_configuration_facts(profile, scope, source_version)
    document["installed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return validate_manifest(document)


def canonical_json(document: Any) -> str:
    """Return deterministic JSON for a validated manifest."""

    validate_manifest(document)
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def load_manifest(path: str | Path) -> dict[str, Any]:
    """Load a manifest using strict UTF-8 and duplicate-member rejection."""

    try:
        if str(path) == "-":
            source = sys.stdin.buffer.read().decode("utf-8")
        else:
            source = Path(path).read_bytes().decode("utf-8")
        document = json.loads(
            source,
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ManifestError(f"invalid UTF-8 JSON: {exc}") from exc
    return validate_manifest(document)


def write_manifest(path: str | Path, document: dict[str, Any]) -> None:
    """Atomically replace ``path`` with canonical manifest JSON."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_json(document).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
    )
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
    parser = argparse.ArgumentParser(description="Write or check a closed installation manifest.")
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--output", type=Path, help="atomically write a new manifest")
    operation.add_argument("--check", type=Path, help="check an existing manifest's configuration facts")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--source-version", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.output is not None:
            write_manifest(args.output, build_manifest(args.profile, args.scope, args.source_version))
            return 0
        document = load_manifest(args.check)
        expected = expected_configuration_facts(args.profile, args.scope, args.source_version)
        return 0 if configuration_facts(document) == expected else 1
    except (ManifestError, OSError) as exc:
        print(f"manifest error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
