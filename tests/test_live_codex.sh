#!/usr/bin/env bash
set -euo pipefail

bundle_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

if [[ "${RUN_CODEX_LIVE:-}" != "1" ]]; then
  printf 'SKIP: Codex live conformance is opt-in; no authentication, network, or mutation performed.\n'
  exit 0
fi

evidence_path="${CODEX_LIVE_EVIDENCE_FILE:-}"
if [[ -z "$evidence_path" || ! -f "$evidence_path" ]]; then
  printf 'UNVERIFIED: provide a reviewable native-runtime evidence file via CODEX_LIVE_EVIDENCE_FILE.\n' >&2
  exit 2
fi

# This entrypoint intentionally consumes evidence exported by a reviewed live
# harness.  There is no stable CLI invocation here, so the default enabled path
# remains dry and read-only; configured pins, model catalogs, and App-task facts
# are never accepted as native effective evidence.
python3 - "$bundle_root" "$evidence_path" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path


root = Path(sys.argv[1])
evidence_path = Path(sys.argv[2])
sys.path.insert(0, str(root / "payload/skills/versatile-dev/scripts"))
import runtime_audit  # noqa: E402


def unverified() -> None:
    print("UNVERIFIED: native effective route evidence is missing, conflicting, or invalid.", file=sys.stderr)
    raise SystemExit(2)


def reject_duplicate_members(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


try:
    document = json.loads(
        evidence_path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_members,
    )
    if not isinstance(document, dict) or set(document) != {"schema_version", "precheck", "audit"}:
        unverified()
    if document["schema_version"] != 1:
        unverified()
    precheck = document["precheck"]
    if not isinstance(precheck, dict) or set(precheck) != {"interface", "runtime_id", "exposed_agent_types"}:
        unverified()
    if precheck["interface"] not in {"native", "native_spawn", "native_spawn_attempt"}:
        unverified()
    if not isinstance(precheck["runtime_id"], str) or not precheck["runtime_id"] or precheck["runtime_id"] == "unknown":
        unverified()
    if precheck["exposed_agent_types"] != ["docs_researcher_luna", "docs_researcher_terra"]:
        unverified()
    audit = document["audit"]
    runtime_audit.validate_document(audit)
    attempt = audit["attempt"]
    required = {
        "requested_agent_type": "docs_researcher_luna",
        "requested_model": "gpt-5.6-luna",
        "requested_effort": "max",
        "interface": "native_spawn",
        "observed_agent_type": "docs_researcher_luna",
        "observed_effective_model": "gpt-5.6-luna",
        "observed_effective_effort": "max",
    }
    if any(attempt.get(field) != expected for field, expected in required.items()):
        unverified()
    for field in ("requested_sandbox", "observed_sandbox", "permission_profile"):
        if not isinstance(attempt.get(field), str) or not attempt[field] or attempt[field] == "unknown":
            unverified()
    evidence_source = attempt["evidence_source"]
    if (
        evidence_source["kind"] != "native_runtime_details"
        or evidence_source["scope"] != "single-attempt"
        or evidence_source["diagnostic_only"] is not False
        or evidence_source["attempt_id"] != attempt["attempt_id"]
        or evidence_source["runtime_id"] != precheck["runtime_id"]
    ):
        unverified()
except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError, runtime_audit.RuntimeAuditError):
    unverified()

print("CONFORMANCE VERIFIED: observed native route evidence is complete and matches the requested Luna/Max tuple.")
print("Observed sandbox and permission metadata were recorded without echoing sensitive values.")
PY
