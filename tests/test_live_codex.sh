#!/usr/bin/env bash
set -euo pipefail

bundle_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

if [[ "${RUN_CODEX_LIVE:-}" != "1" ]]; then
  printf 'SKIP: optional live schema review is opt-in; no authentication, network, or mutation performed.\n'
  exit 0
fi

evidence_path="${CODEX_LIVE_EVIDENCE_FILE:-}"
if [[ -z "$evidence_path" || ! -f "$evidence_path" ]]; then
  printf 'UNVERIFIED: provide a reviewable native-runtime evidence file via CODEX_LIVE_EVIDENCE_FILE.\n' >&2
  exit 2
fi

# This is a schema-review harness only.  No stable authenticated live CLI is
# available in this bundle, so even schema-valid evidence must remain
# UNVERIFIED.  Configured pins, model catalogs, and App-task facts are never
# accepted as native effective evidence, and no evidence value is echoed.
PYTHONDONTWRITEBYTECODE=1 python3 - "$bundle_root" "$evidence_path" <<'PY'
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path


root = Path(sys.argv[1])
evidence_path = Path(sys.argv[2])
sys.path.insert(0, str(root / "payload/skills/versatile-dev/scripts"))
import runtime_audit  # noqa: E402


REQUESTED_LUNA = ("docs_researcher_luna", "gpt-5.6-luna", "max")
UNKNOWN_TRIPLE = ("unknown", "unknown", "unknown")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SENSITIVE_TEXT = re.compile(
    r"(?:secret|password|token|api[_-]?key|access[_-]?key|private[_-]?key|"
    r"credential|bearer|authorization|-----begin)",
    re.IGNORECASE,
)


def unverified() -> None:
    print(
        "UNVERIFIED: schema-valid evidence is not authenticated fresh live conformance; "
        "this entrypoint has no authenticated fresh-task runner.",
        file=sys.stderr,
    )
    raise SystemExit(2)


def reject_duplicate_members(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def reject_unsafe_metadata(value: object) -> None:
    if isinstance(value, str):
        if any(
            ord(character) < 0x20
            or ord(character) == 0x7F
            or unicodedata.category(character) in {"Cc", "Cf"}
            or character in {"\u2028", "\u2029"}
            for character in value
        ):
            raise ValueError("control metadata")
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ValueError("surrogate metadata")
        if SENSITIVE_TEXT.search(value):
            raise ValueError("sensitive metadata")
    elif isinstance(value, dict):
        for key, item in value.items():
            reject_unsafe_metadata(key)
            reject_unsafe_metadata(item)
    elif isinstance(value, list):
        for item in value:
            reject_unsafe_metadata(item)


try:
    document = json.loads(
        evidence_path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_members,
        parse_constant=reject_constant,
    )
    reject_unsafe_metadata(document)
    if not isinstance(document, dict) or set(document) != {"schema_version", "precheck", "audit"}:
        unverified()
    if document["schema_version"] != 1:
        unverified()

    precheck = document["precheck"]
    if not isinstance(precheck, dict) or set(precheck) != {
        "interface",
        "runtime_id",
        "task_packet_hash",
        "exposed_agent_types",
    }:
        unverified()
    if precheck["interface"] != "native_spawn":
        unverified()
    if not isinstance(precheck["runtime_id"], str) or not precheck["runtime_id"] or precheck["runtime_id"] == "unknown":
        unverified()
    if not isinstance(precheck["task_packet_hash"], str) or HASH_RE.fullmatch(precheck["task_packet_hash"]) is None:
        unverified()
    if precheck["exposed_agent_types"] != ["docs_researcher_luna", "docs_researcher_terra"]:
        unverified()

    audit = document["audit"]
    runtime_audit.validate_document(audit)
    attempt = audit["attempt"]
    if attempt["task_packet_hash"] != precheck["task_packet_hash"]:
        unverified()
    if attempt["interface"] != precheck["interface"]:
        unverified()

    requested = (
        attempt["requested_agent_type"],
        attempt["requested_model"],
        attempt["requested_effort"],
    )
    observed = (
        attempt["observed_agent_type"],
        attempt["observed_effective_model"],
        attempt["observed_effective_effort"],
    )
    configured = (
        attempt["configured_agent_type"],
        attempt["configured_model"],
        attempt["configured_effort"],
    )
    if requested != REQUESTED_LUNA or observed != REQUESTED_LUNA:
        unverified()
    if configured not in {REQUESTED_LUNA, UNKNOWN_TRIPLE}:
        unverified()
    if attempt["status"] != "task_success" or attempt["failure_class"] != "NONE":
        unverified()
    if attempt["fallback_attempt"] != 0:
        unverified()
    for field in ("requested_sandbox", "observed_sandbox", "permission_profile"):
        if not isinstance(attempt.get(field), str) or not attempt[field] or attempt[field] == "unknown":
            unverified()

    evidence_source = attempt["evidence_source"]
    if (
        evidence_source["kind"] != "native_runtime_details"
        or evidence_source["interface"] != precheck["interface"]
        or evidence_source["scope"] != "single-attempt"
        or evidence_source["diagnostic_only"] is not False
        or evidence_source["attempt_id"] != attempt["attempt_id"]
        or evidence_source["runtime_id"] != precheck["runtime_id"]
    ):
        unverified()
except Exception:
    unverified()

# Deliberately nonzero: the schema sample is not proof of an authenticated,
# fresh native task, and this bundle has no genuine live runner to establish it.
unverified()
PY
