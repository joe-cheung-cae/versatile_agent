#!/usr/bin/env python3
"""Replay the closed native research-route state machine.

The input is intentionally small and closed.  It has exactly these top-level
fields::

    {
      "schema_version": 1,
      "task_packet_hash": "sha256:<64 lowercase hex digits>",
      "runtime_records": <runtime_records schema-v1 document>,
      "events": [ ... ]
    }

Every event repeats the packet hash and is one of ``precheck``,
``luna_result``, ``dispatch_terra``, or ``terra_result``.  The precheck selects
one active-interface record.  Later events repeat that ID as
``precheck_runtime_id`` and select independent native attempt records through
their own ``runtime_id``.  Result events carry ``attempt_id``,
``fallback_attempt``, ``status``, and ``failure_class``.  A routing failure
also carries the closed ``routing_failure`` enum and, except for a
record-proven route mismatch, a same-attempt ``routing_evidence`` object.  The
runtime document is validated and queried by :mod:`runtime_records`; this
module never treats a probe, profile, catalog, or App task as native effective
evidence.

``decide`` is pure replay: it has no persistence, subprocesses, network, auth,
agent, or App-task calls.  The CLI prints deterministic JSON and returns 2 for
malformed input.  Valid but incomplete or conflicting evidence is represented
as a terminal ``STOP_UNVERIFIED`` decision.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any


def _load_runtime_records() -> Any:
    """Load the sibling P1-1 helper in both CLI and importlib test modes."""

    try:
        import runtime_records  # type: ignore[import-not-found]

        return runtime_records
    except ModuleNotFoundError:
        helper_path = Path(__file__).with_name("runtime_records.py")
        spec = importlib.util.spec_from_file_location("runtime_records", helper_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"unable to load runtime-record helper: {helper_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


runtime_records = _load_runtime_records()


SCHEMA_VERSION = 1
STATE_PRECHECK = "PRECHECK"
STATE_LUNA_PENDING = "LUNA_PENDING"
STATE_DONE_LUNA = "DONE_LUNA"
STATE_FALLBACK_PENDING = "FALLBACK_PENDING"
STATE_TERRA_PENDING = "TERRA_PENDING"
STATE_DONE_TERRA = "DONE_TERRA"
STATE_STOP_FAILED = "STOP_FAILED"
STATE_STOP_UNVERIFIED = "STOP_UNVERIFIED"

TERMINAL_STATES = frozenset(
    {
        STATE_DONE_LUNA,
        STATE_DONE_TERRA,
        STATE_STOP_FAILED,
        STATE_STOP_UNVERIFIED,
    }
)

ROUTES = {
    "luna": {
        "agent_type": "docs_researcher_luna",
        "model": "gpt-5.6-luna",
        "effort": "max",
    },
    "terra": {
        "agent_type": "docs_researcher_terra",
        "model": "gpt-5.6-terra",
        "effort": "high",
    },
}

ROUTING_FAILURES = frozenset(
    {
        "requested_agent_unavailable",
        "requested_model_unavailable",
        "model_access_denied",
        "requested_effort_unsupported",
        "native_spawn_rejected",
        "native_route_mismatch",
    }
)

FAILURE_CLASSES = frozenset(
    {
        "NONE",
        "NATIVE_ROUTING_FAILURE",
        "ROUTE_METADATA_MISSING",
        "ROUTE_METADATA_CONFLICT",
        "TASK_FAILURE",
        "TIMEOUT",
        "UNKNOWN_EXCEPTION",
    }
)

STATUSES = frozenset(
    {
        "task_success",
        "routing_failure",
        "content_failure",
        "tool_failure",
        "task_failure",
        "timeout",
        "unknown_exception",
    }
)

TOP_LEVEL_FIELDS = {"schema_version", "task_packet_hash", "runtime_records", "events"}
COMMON_EVENT_FIELDS = {"event", "task_packet_hash", "fallback_attempt"}
EVENT_FIELDS = {
    "precheck": COMMON_EVENT_FIELDS | {"runtime_id"},
    "luna_result": COMMON_EVENT_FIELDS
    | {
        "attempt_id",
        "precheck_runtime_id",
        "runtime_id",
        "status",
        "failure_class",
        "routing_failure",
        "routing_evidence",
    },
    "dispatch_terra": COMMON_EVENT_FIELDS
    | {"attempt_id", "precheck_runtime_id", "runtime_id"},
    "terra_result": COMMON_EVENT_FIELDS
    | {
        "attempt_id",
        "precheck_runtime_id",
        "runtime_id",
        "status",
        "failure_class",
        "routing_failure",
        "routing_evidence",
    },
}
REQUIRED_EVENT_FIELDS = {
    "precheck": COMMON_EVENT_FIELDS | {"runtime_id"},
    "luna_result": COMMON_EVENT_FIELDS
    | {"attempt_id", "precheck_runtime_id", "runtime_id", "status", "failure_class"},
    "dispatch_terra": COMMON_EVENT_FIELDS | {"attempt_id", "precheck_runtime_id", "runtime_id"},
    "terra_result": COMMON_EVENT_FIELDS
    | {"attempt_id", "precheck_runtime_id", "runtime_id", "status", "failure_class"},
}

_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class RouteResearchError(ValueError):
    """Raised when the route document or event stream is malformed."""


def _json_member_label(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True)
    except (TypeError, ValueError):
        return repr(value)


def _reject_duplicate_json_members(pairs: list[tuple[Any, Any]]) -> dict[str, Any]:
    """Build one JSON object while rejecting duplicate member names."""

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _error("document", f"duplicate JSON member name: {_json_member_label(key)}")
        result[key] = value
    return result


def _error(location: str, message: str) -> RouteResearchError:
    return RouteResearchError(f"{location}: {message}")


def _require_object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _error(location, "must be an object")
    return value


def _require_string(value: Any, location: str, *, token: bool = False) -> str:
    if not isinstance(value, str):
        raise _error(location, "must be a string")
    if not value or value != value.strip():
        raise _error(location, "must be a non-empty canonical string")
    if token and (value == "unknown" or _TOKEN_RE.fullmatch(value) is None):
        raise _error(location, "must be a canonical non-unknown token")
    return value


def _require_hash(value: Any, location: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise _error(location, "must be sha256: followed by 64 lowercase hexadecimal digits")
    return value


def _require_int(value: Any, location: str, *, maximum: int | None = None) -> int:
    if type(value) is not int:
        raise _error(location, "must be an integer")
    if value < 0 or (maximum is not None and value > maximum):
        limit = f" and <= {maximum}" if maximum is not None else ""
        raise _error(location, f"must be >= 0{limit}")
    return value


def _field_labels(values: set[Any]) -> list[str]:
    labels: list[str] = []
    for value in values:
        try:
            labels.append(repr(value))
        except Exception:
            labels.append(f"<{type(value).__name__}>")
    return sorted(labels)


def _check_fields(value: dict[str, Any], allowed: set[str], required: set[str], location: str) -> None:
    extra = set(value) - allowed
    if extra:
        raise _error(location, f"unsupported fields: {_field_labels(extra)}")
    missing = required - set(value)
    if missing:
        raise _error(location, f"missing required fields: {_field_labels(missing)}")


def _validate_routing_evidence(value: Any, location: str) -> dict[str, str]:
    evidence = _require_object(value, location)
    fields = {"kind", "runtime_id", "attempt_id", "detail"}
    _check_fields(evidence, fields, fields, location)
    kind = _require_string(evidence["kind"], f"{location}.kind")
    if kind not in {
        "requested_agent_unavailable",
        "requested_model_unavailable",
        "model_access_denied",
        "requested_effort_unsupported",
        "native_spawn_rejected",
    }:
        raise _error(f"{location}.kind", "must be one of the explicit routing-failure triggers")
    runtime_id = _require_string(evidence["runtime_id"], f"{location}.runtime_id", token=True)
    attempt_id = _require_string(evidence["attempt_id"], f"{location}.attempt_id", token=True)
    detail = _require_string(evidence["detail"], f"{location}.detail")
    return {"kind": kind, "runtime_id": runtime_id, "attempt_id": attempt_id, "detail": detail}


def _validate_event(event: Any, index: int, task_packet_hash: str) -> dict[str, Any]:
    location = f"events[{index}]"
    data = _require_object(event, location)
    event_name = data.get("event")
    if not isinstance(event_name, str) or event_name not in EVENT_FIELDS:
        raise _error(f"{location}.event", f"unsupported event: {event_name!r}")
    _check_fields(data, EVENT_FIELDS[event_name], REQUIRED_EVENT_FIELDS[event_name], location)

    event_hash = _require_hash(data["task_packet_hash"], f"{location}.task_packet_hash")
    if event_hash != task_packet_hash:
        raise _error(f"{location}.task_packet_hash", "must equal the document task_packet_hash")
    fallback_attempt = _require_int(data["fallback_attempt"], f"{location}.fallback_attempt", maximum=1)
    if event_name in {"precheck", "luna_result"} and fallback_attempt != 0:
        raise _error(f"{location}.fallback_attempt", "must be 0 before Terra dispatch")
    if event_name in {"dispatch_terra", "terra_result"} and fallback_attempt != 1:
        raise _error(f"{location}.fallback_attempt", "must be exactly 1 for Terra")

    _require_string(data["runtime_id"], f"{location}.runtime_id", token=True)
    if event_name in {"luna_result", "terra_result", "dispatch_terra"}:
        _require_string(data["attempt_id"], f"{location}.attempt_id", token=True)
        _require_string(data["precheck_runtime_id"], f"{location}.precheck_runtime_id", token=True)
    if event_name in {"luna_result", "terra_result"}:
        status = _require_string(data["status"], f"{location}.status")
        if status not in STATUSES:
            raise _error(f"{location}.status", f"unsupported status: {status}")
        failure_class = _require_string(data["failure_class"], f"{location}.failure_class")
        if failure_class not in FAILURE_CLASSES:
            raise _error(f"{location}.failure_class", f"unsupported failure class: {failure_class}")
        if "routing_failure" in data:
            routing_failure = _require_string(data["routing_failure"], f"{location}.routing_failure")
            if routing_failure not in ROUTING_FAILURES:
                raise _error(
                    f"{location}.routing_failure",
                    f"unsupported routing failure: {routing_failure}",
                )
        if "routing_evidence" in data:
            _validate_routing_evidence(data["routing_evidence"], f"{location}.routing_evidence")
        if status == "routing_failure" and "routing_failure" not in data:
            raise _error(f"{location}.routing_failure", "is required for routing_failure status")
        if status == "routing_failure":
            trigger = data["routing_failure"]
            if trigger != "native_route_mismatch" and "routing_evidence" not in data:
                raise _error(
                    f"{location}.routing_evidence",
                    "is required for an explicit native routing rejection",
                )
    return data


def validate_document(document: Any) -> dict[str, Any]:
    """Validate the route document and its nested P1-1 evidence."""

    data = _require_object(document, "document")
    _check_fields(data, TOP_LEVEL_FIELDS, TOP_LEVEL_FIELDS, "document")
    if type(data["schema_version"]) is not int or data["schema_version"] != SCHEMA_VERSION:
        raise _error("document.schema_version", f"must be {SCHEMA_VERSION}")
    task_packet_hash = _require_hash(data["task_packet_hash"], "document.task_packet_hash")
    _require_object(data["runtime_records"], "document.runtime_records")
    try:
        runtime_records.validate_document(data["runtime_records"])
    except Exception as exc:
        raise _error("document.runtime_records", str(exc)) from exc
    if not isinstance(data["events"], list):
        raise _error("document.events", "must be a list")
    for index, event in enumerate(data["events"]):
        _validate_event(event, index, task_packet_hash)
    return data


def _initial_output(task_packet_hash: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "state": STATE_PRECHECK,
        "next_action": "precheck",
        "task_packet_hash": task_packet_hash,
        "fallback_attempt": 0,
        "terminal": False,
        "reason": "awaiting_precheck",
        "failure_class": "NONE",
        "precheck_runtime_id": None,
        "luna_attempt_id": None,
        "luna_attempt_runtime_id": None,
        "terra_attempt_id": None,
        "terra_attempt_runtime_id": None,
        "last_runtime_id": None,
        "runtime_ids": [],
        "attempt_ids": [],
        "requested_route": None,
        "effective_route": None,
        "evidence": None,
    }


def _record_runtime_id(output: dict[str, Any], runtime_id: str) -> None:
    if runtime_id not in output["runtime_ids"]:
        output["runtime_ids"].append(runtime_id)
    output["last_runtime_id"] = runtime_id


def _event_evidence(event: dict[str, Any], record: dict[str, Any] | None = None) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "event": event["event"],
        "runtime_id": event.get("runtime_id"),
        "precheck_runtime_id": event.get("precheck_runtime_id"),
        "attempt_id": event.get("attempt_id"),
        "status": event.get("status"),
        "routing_failure": event.get("routing_failure"),
        "routing_evidence": event.get("routing_evidence"),
    }
    if record is not None:
        evidence["record_evidence_source"] = record["evidence_source"]
    return evidence


def _set_decision(
    output: dict[str, Any],
    *,
    state: str,
    next_action: str,
    reason: str,
    failure_class: str,
    requested_route: dict[str, str] | None = None,
    effective_route: dict[str, str] | None = None,
    evidence: dict[str, Any] | None = None,
) -> None:
    output["state"] = state
    output["next_action"] = next_action
    output["terminal"] = state in TERMINAL_STATES
    output["reason"] = reason
    output["failure_class"] = failure_class
    output["requested_route"] = requested_route
    output["effective_route"] = effective_route
    output["evidence"] = evidence


def _select_record(document: dict[str, Any], runtime_id: str) -> dict[str, Any] | None:
    try:
        result = runtime_records.query_record(document, runtime_id=runtime_id)
    except Exception:
        return None
    return result["record"]


def _precheck(output: dict[str, Any], document: dict[str, Any], event: dict[str, Any]) -> None:
    runtime_id = event["runtime_id"]
    _record_runtime_id(output, runtime_id)
    record = _select_record(document, runtime_id)
    evidence = _event_evidence(event, record)
    if record is None:
        _set_decision(
            output,
            state=STATE_STOP_UNVERIFIED,
            next_action="none",
            reason="precheck_runtime_unavailable_or_ambiguous",
            failure_class="ROUTE_METADATA_MISSING",
            evidence=evidence,
        )
        return
    if record["interface_kind"] not in {"native_spawn_attempt", "native_capability_inventory"}:
        _set_decision(
            output,
            state=STATE_STOP_UNVERIFIED,
            next_action="none",
            reason="precheck_requires_native_spawn_interface",
            failure_class="ROUTE_METADATA_CONFLICT",
            evidence=evidence,
        )
        return
    if record["diagnostic_only"] is not False:
        _set_decision(
            output,
            state=STATE_STOP_UNVERIFIED,
            next_action="none",
            reason="precheck_diagnostic_evidence_is_not_effective",
            failure_class="ROUTE_METADATA_MISSING",
            evidence=evidence,
        )
        return
    if record["multi_agent_generation"] != "v2":
        _set_decision(
            output,
            state=STATE_STOP_UNVERIFIED,
            next_action="none",
            reason="precheck_requires_v2_native_generation",
            failure_class="ROUTE_METADATA_CONFLICT",
            evidence=evidence,
        )
        return
    exposed = record["exposed_agent_types"]
    required = {ROUTES["luna"]["agent_type"], ROUTES["terra"]["agent_type"]}
    if not isinstance(exposed, list) or not exposed:
        _set_decision(
            output,
            state=STATE_STOP_UNVERIFIED,
            next_action="none",
            reason="precheck_agent_exposure_missing_or_unknown",
            failure_class="ROUTE_METADATA_MISSING",
            evidence=evidence,
        )
        return
    if not _canonical_capability_list(exposed):
        _set_decision(
            output,
            state=STATE_STOP_UNVERIFIED,
            next_action="none",
            reason="precheck_capability_exposure_is_noncanonical",
            failure_class="ROUTE_METADATA_CONFLICT",
            evidence=evidence,
        )
        return
    if not required.issubset(exposed):
        _set_decision(
            output,
            state=STATE_STOP_UNVERIFIED,
            next_action="none",
            reason="precheck_same_record_dual_agent_exposure_required",
            failure_class="ROUTE_METADATA_CONFLICT",
            evidence=evidence,
        )
        return
    output["precheck_runtime_id"] = runtime_id
    _set_decision(
        output,
        state=STATE_LUNA_PENDING,
        next_action="spawn_luna",
        reason="precheck_verified_same_record_dual_agent_exposure",
        failure_class="NONE",
        requested_route=ROUTES["luna"].copy(),
        evidence=evidence,
    )


def _effective_route_from_record(record: dict[str, Any]) -> dict[str, str] | None:
    observed = record.get("observed")
    if not isinstance(observed, dict):
        return None
    fields = {
        "agent_type": observed.get("effective_agent_type"),
        "model": observed.get("effective_model"),
        "effort": observed.get("effective_effort"),
    }
    if any(not isinstance(value, str) or not value or value == "unknown" or value != value.strip() for value in fields.values()):
        return None
    return fields  # type: ignore[return-value]


def _canonical_capability_token(value: Any) -> bool:
    return isinstance(value, str) and _TOKEN_RE.fullmatch(value) is not None and value != "unknown"


def _canonical_capability_list(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    if not all(isinstance(item, str) for item in value):
        return False
    if len(value) != len(set(value)):
        return False
    return all(_canonical_capability_token(item) for item in value)


def _canonical_capability_map(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if not all(_canonical_capability_token(key) for key in value):
        return False
    return all(_canonical_capability_list(efforts) for efforts in value.values())


def _query_effective_route(
    document: dict[str, Any], runtime_id: str, requested_route: dict[str, str]
) -> tuple[str, dict[str, str] | None, dict[str, Any] | None, str]:
    """Select one record, preflight its actual route through P1-1, then compare."""
    try:
        selected = runtime_records.query_record(
            document,
            runtime_id=runtime_id,
            interface_kind="native_spawn_attempt",
        )
    except Exception:
        return "unverified", None, None, "ROUTE_METADATA_MISSING"

    record = selected["record"]
    if not (
        _canonical_capability_list(record["exposed_agent_types"])
        and _canonical_capability_list(record["model_support"])
        and _canonical_capability_map(record["effort_support"])
    ):
        return "unverified", None, record, "ROUTE_METADATA_CONFLICT"
    effective_route = _effective_route_from_record(record)
    if effective_route is None:
        return "unverified", None, record, "ROUTE_METADATA_MISSING"

    # Ask P1-1 to preflight the actual tuple from this same selected record.
    # This preserves its native/non-diagnostic/atomic support checks without
    # depending on exception wording to classify a requested-route mismatch.
    try:
        validated = runtime_records.query_record(
            document,
            runtime_id=runtime_id,
            interface_kind="native_spawn_attempt",
            require_effective_agent_type=effective_route["agent_type"],
            require_effective_model=effective_route["model"],
            require_effective_effort=effective_route["effort"],
        )
    except Exception:
        return "unverified", None, record, "ROUTE_METADATA_CONFLICT"

    record = validated["record"]
    if effective_route == requested_route:
        return "exact", effective_route, record, ""
    return "mismatch", effective_route, record, "NATIVE_ROUTING_FAILURE"


def _validate_requested_attempt(
    document: dict[str, Any],
    *,
    runtime_id: str,
    requested_route: dict[str, str],
) -> tuple[str, dict[str, Any] | None, str]:
    """Validate one non-diagnostic native attempt's requested route fields."""

    record = _select_record(document, runtime_id)
    if record is None:
        return "unverified", None, "ROUTE_METADATA_MISSING"
    if record["interface_kind"] != "native_spawn_attempt":
        return "unverified", record, "ROUTE_METADATA_CONFLICT"
    if record["diagnostic_only"] is not False:
        return "unverified", record, "ROUTE_METADATA_MISSING"
    observed = record.get("observed")
    if not isinstance(observed, dict):
        return "unverified", record, "ROUTE_METADATA_MISSING"
    for field, expected in (
        ("agent_type", requested_route["agent_type"]),
        ("model", requested_route["model"]),
        ("effort", requested_route["effort"]),
    ):
        value = observed.get(field)
        if not isinstance(value, str) or not value or value == "unknown" or value != value.strip():
            return "unverified", record, "ROUTE_METADATA_MISSING"
        if value != expected:
            return "unverified", record, "ROUTE_METADATA_CONFLICT"
    return "accepted", record, ""


def _validate_rejection_attempt(
    document: dict[str, Any],
    *,
    runtime_id: str,
    attempt_id: str,
    requested_route: dict[str, str],
    trigger: str,
) -> tuple[str, dict[str, str] | None, dict[str, Any] | None, str]:
    """Validate a same-attempt native rejection without inventing effective data."""

    requested_status, record, requested_failure = _validate_requested_attempt(
        document,
        runtime_id=runtime_id,
        requested_route=requested_route,
    )
    if requested_status != "accepted":
        return "unverified", None, record, requested_failure

    if not (
        _canonical_capability_list(record["exposed_agent_types"])
        and _canonical_capability_list(record["model_support"])
        and _canonical_capability_map(record["effort_support"])
    ):
        return "unverified", None, record, "ROUTE_METADATA_CONFLICT"

    observed = record["observed"]
    exposed = record["exposed_agent_types"]
    models = record["model_support"]
    efforts = record["effort_support"]
    requested_agent = requested_route["agent_type"]
    requested_model = requested_route["model"]
    requested_effort = requested_route["effort"]
    if trigger == "requested_agent_unavailable":
        if requested_agent in exposed:
            return "conflict", None, record, "ROUTE_METADATA_CONFLICT"
    elif trigger == "requested_model_unavailable":
        if requested_model in models:
            return "conflict", None, record, "ROUTE_METADATA_CONFLICT"
    elif trigger == "requested_effort_unsupported":
        if requested_model not in models:
            return "unverified", None, record, "ROUTE_METADATA_MISSING"
        supported_efforts = efforts.get(requested_model)
        if not isinstance(supported_efforts, list):
            return "unverified", None, record, "ROUTE_METADATA_MISSING"
        if requested_effort in supported_efforts:
            return "conflict", None, record, "ROUTE_METADATA_CONFLICT"
    elif trigger not in {"model_access_denied", "native_spawn_rejected"}:
        return "unverified", None, record, "ROUTE_METADATA_CONFLICT"

    effective_names = {"effective_agent_type", "effective_model", "effective_effort"}
    effective_keys = set(observed) & effective_names
    if not effective_keys:
        return "accepted", None, record, "NATIVE_ROUTING_FAILURE"
    if effective_keys != effective_names:
        return "unverified", None, record, "ROUTE_METADATA_MISSING"
    effective_route = _effective_route_from_record(record)
    if effective_route is None:
        return "unverified", None, record, "ROUTE_METADATA_MISSING"
    try:
        runtime_records.query_record(
            document,
            runtime_id=runtime_id,
            interface_kind="native_spawn_attempt",
            require_effective_agent_type=effective_route["agent_type"],
            require_effective_model=effective_route["model"],
            require_effective_effort=effective_route["effort"],
        )
    except Exception:
        return "unverified", None, record, "ROUTE_METADATA_CONFLICT"
    # An explicit rejection and a complete effective tuple are contradictory
    # evidence.  A complete mismatch must be reported as native_route_mismatch
    # instead of being relabeled as the synthetic rejection trigger.
    del attempt_id
    return "conflict", effective_route, record, "ROUTE_METADATA_CONFLICT"


def _failure_class_for_status(status: str) -> str:
    if status == "task_success":
        return "NONE"
    if status == "routing_failure":
        return "NATIVE_ROUTING_FAILURE"
    if status == "timeout":
        return "TIMEOUT"
    if status == "unknown_exception":
        return "UNKNOWN_EXCEPTION"
    return "TASK_FAILURE"


def _stop_unverified_result(
    output: dict[str, Any],
    event: dict[str, Any],
    *,
    reason: str,
    failure_class: str = "ROUTE_METADATA_CONFLICT",
    record: dict[str, Any] | None = None,
    effective_route: dict[str, str] | None = None,
) -> None:
    _set_decision(
        output,
        state=STATE_STOP_UNVERIFIED,
        next_action="none",
        reason=reason,
        failure_class=failure_class,
        requested_route=ROUTES["luna" if event["event"] == "luna_result" else "terra"].copy(),
        effective_route=effective_route,
        evidence=_event_evidence(event, record),
    )


def _process_result(
    output: dict[str, Any],
    document: dict[str, Any],
    event: dict[str, Any],
    *,
    route_name: str,
) -> None:
    requested_route = ROUTES[route_name]
    runtime_id = event["runtime_id"]
    _record_runtime_id(output, runtime_id)
    attempt_id = event["attempt_id"]
    if event["precheck_runtime_id"] != output["precheck_runtime_id"]:
        _stop_unverified_result(
            output,
            event,
            reason="attempt_precheck_runtime_binding_conflicts",
            failure_class="ROUTE_METADATA_CONFLICT",
        )
        return
    if runtime_id == output["precheck_runtime_id"]:
        _stop_unverified_result(
            output,
            event,
            reason="attempt_must_use_independent_native_runtime_record",
            failure_class="ROUTE_METADATA_CONFLICT",
        )
        return
    requested_status, requested_record, requested_failure = _validate_requested_attempt(
        document,
        runtime_id=runtime_id,
        requested_route=requested_route,
    )
    if requested_status != "accepted":
        _stop_unverified_result(
            output,
            event,
            reason="native_attempt_requested_route_unverified",
            failure_class=requested_failure,
            record=requested_record,
        )
        return
    if route_name == "luna":
        if output["luna_attempt_id"] is not None or output["luna_attempt_runtime_id"] is not None:
            _stop_unverified_result(
                output,
                event,
                reason="luna_attempt_reuse",
                failure_class="ROUTE_METADATA_CONFLICT",
            )
            return
        if runtime_id == output["terra_attempt_runtime_id"]:
            _stop_unverified_result(
                output,
                event,
                reason="luna_and_terra_may_not_reuse_attempt_runtime",
                failure_class="ROUTE_METADATA_CONFLICT",
            )
            return
        output["luna_attempt_id"] = attempt_id
        output["luna_attempt_runtime_id"] = runtime_id
    else:
        if event["attempt_id"] != output["terra_attempt_id"]:
            _stop_unverified_result(
                output,
                event,
                reason="terra_result_attempt_id_must_match_dispatch",
                failure_class="ROUTE_METADATA_CONFLICT",
            )
            return
        if runtime_id != output["terra_attempt_runtime_id"]:
            _stop_unverified_result(
                output,
                event,
                reason="terra_result_runtime_id_must_match_dispatch",
                failure_class="ROUTE_METADATA_CONFLICT",
            )
            return
    status = event["status"]
    expected_failure_class = _failure_class_for_status(status)
    if event["failure_class"] != expected_failure_class:
        _stop_unverified_result(
            output,
            event,
            reason="event_status_and_failure_class_conflict",
            failure_class="ROUTE_METADATA_CONFLICT",
        )
        return
    if status != "routing_failure" and (
        "routing_failure" in event or "routing_evidence" in event
    ):
        _stop_unverified_result(
            output,
            event,
            reason="non_routing_status_may_not_include_routing_metadata",
            failure_class="ROUTE_METADATA_CONFLICT",
        )
        return

    trigger = event.get("routing_failure")
    if status == "routing_failure" and trigger != "native_route_mismatch":
        rejection_status, effective_route, record, rejection_failure = _validate_rejection_attempt(
            document,
            runtime_id=runtime_id,
            attempt_id=attempt_id,
            requested_route=requested_route,
            trigger=trigger,
        )
        evidence = _event_evidence(event, record)
        routing_evidence = event.get("routing_evidence")
        if not isinstance(routing_evidence, dict):
            _stop_unverified_result(
                output,
                event,
                reason="routing_rejection_evidence_missing",
                failure_class="ROUTE_METADATA_MISSING",
                record=record,
                effective_route=effective_route,
            )
            return
        if (
            routing_evidence.get("kind") != trigger
            or routing_evidence.get("runtime_id") != runtime_id
            or routing_evidence.get("attempt_id") != attempt_id
        ):
            _stop_unverified_result(
                output,
                event,
                reason="routing_rejection_evidence_is_not_same_attempt",
                failure_class="ROUTE_METADATA_CONFLICT",
                record=record,
                effective_route=effective_route,
            )
            return
        if rejection_status != "accepted":
            _stop_unverified_result(
                output,
                event,
                reason="explicit_routing_rejection_evidence_unverified_or_conflicting",
                failure_class=rejection_failure,
                record=record,
                effective_route=effective_route,
            )
            return
        if route_name == "luna":
            output["fallback_attempt"] = 1
            _set_decision(
                output,
                state=STATE_FALLBACK_PENDING,
                next_action="spawn_terra",
                reason=f"luna_{trigger}",
                failure_class="NATIVE_ROUTING_FAILURE",
                requested_route=requested_route.copy(),
                effective_route=None,
                evidence=evidence,
            )
            return
        _set_decision(
            output,
            state=STATE_STOP_FAILED,
            next_action="none",
            reason=f"terra_{trigger}",
            failure_class="NATIVE_ROUTING_FAILURE",
            requested_route=requested_route.copy(),
            effective_route=None,
            evidence=evidence,
        )
        return

    route_status, effective_route, record, route_failure = _query_effective_route(
        document, runtime_id, requested_route
    )
    evidence = _event_evidence(event, record)
    if route_status == "unverified":
        _stop_unverified_result(
            output,
            event,
            reason="native_effective_route_unverified",
            failure_class=route_failure,
            record=record,
            effective_route=effective_route,
        )
        return

    if status == "unknown_exception":
        _set_decision(
            output,
            state=STATE_STOP_UNVERIFIED,
            next_action="none",
            reason=f"{route_name}_unknown_exception_unverified",
            failure_class="UNKNOWN_EXCEPTION",
            requested_route=requested_route.copy(),
            effective_route=effective_route,
            evidence=evidence,
        )
        return

    if status == "task_success":
        if route_status == "exact":
            state = STATE_DONE_LUNA if route_name == "luna" else STATE_DONE_TERRA
            _set_decision(
                output,
                state=state,
                next_action="none",
                reason=f"{route_name}_task_success",
                failure_class="NONE",
                requested_route=requested_route.copy(),
                effective_route=effective_route,
                evidence=evidence,
            )
            return
        if route_name == "luna":
            output["fallback_attempt"] = 1
            _set_decision(
                output,
                state=STATE_FALLBACK_PENDING,
                next_action="spawn_terra",
                reason="luna_native_route_mismatch",
                failure_class="NATIVE_ROUTING_FAILURE",
                requested_route=requested_route.copy(),
                effective_route=effective_route,
                evidence=evidence,
            )
            return
        _set_decision(
            output,
            state=STATE_STOP_FAILED,
            next_action="none",
            reason="terra_native_route_mismatch",
            failure_class="NATIVE_ROUTING_FAILURE",
            requested_route=requested_route.copy(),
            effective_route=effective_route,
            evidence=evidence,
        )
        return

    if status == "routing_failure":
        if trigger == "native_route_mismatch" and route_status != "mismatch":
            _stop_unverified_result(
                output,
                event,
                reason="routing_failure_claim_conflicts_with_effective_route",
                failure_class="ROUTE_METADATA_CONFLICT",
                record=record,
                effective_route=effective_route,
            )
            return
        if event.get("routing_evidence") is not None:
            _stop_unverified_result(
                output,
                event,
                reason="native_route_mismatch_may_not_use_synthetic_rejection_evidence",
                failure_class="ROUTE_METADATA_CONFLICT",
                record=record,
                effective_route=effective_route,
            )
            return
        if route_name == "luna":
            output["fallback_attempt"] = 1
            _set_decision(
                output,
                state=STATE_FALLBACK_PENDING,
                next_action="spawn_terra",
                reason=f"luna_{trigger}",
                failure_class="NATIVE_ROUTING_FAILURE",
                requested_route=requested_route.copy(),
                effective_route=effective_route,
                evidence=evidence,
            )
            return
        _set_decision(
            output,
            state=STATE_STOP_FAILED,
            next_action="none",
            reason=f"terra_{trigger}",
            failure_class="NATIVE_ROUTING_FAILURE",
            requested_route=requested_route.copy(),
            effective_route=effective_route,
            evidence=evidence,
        )
        return

    # The metadata was complete before this branch.  Execution/content failure
    # is therefore terminal and never authorizes Terra or another fallback.
    _set_decision(
        output,
        state=STATE_STOP_FAILED,
        next_action="none",
        reason=f"{route_name}_{status}",
        failure_class=expected_failure_class,
        requested_route=requested_route.copy(),
        effective_route=effective_route,
        evidence=evidence,
    )


def _dispatch_terra(output: dict[str, Any], document: dict[str, Any], event: dict[str, Any]) -> None:
    if output["fallback_attempt"] != 1:
        _stop_unverified_result(
            output,
            event,
            reason="fallback_attempt_counter_is_not_one",
            failure_class="ROUTE_METADATA_CONFLICT",
        )
        return
    if event["precheck_runtime_id"] != output["precheck_runtime_id"]:
        _stop_unverified_result(
            output,
            event,
            reason="terra_dispatch_precheck_runtime_binding_conflicts",
            failure_class="ROUTE_METADATA_CONFLICT",
        )
        return
    runtime_id = event["runtime_id"]
    if event["attempt_id"] == output["luna_attempt_id"]:
        _stop_unverified_result(
            output,
            event,
            reason="terra_attempt_id_must_differ_from_luna_attempt",
            failure_class="ROUTE_METADATA_CONFLICT",
        )
        return
    if runtime_id in {
        output["precheck_runtime_id"],
        output["luna_attempt_runtime_id"],
    }:
        _stop_unverified_result(
            output,
            event,
            reason="terra_dispatch_must_use_independent_attempt_runtime",
            failure_class="ROUTE_METADATA_CONFLICT",
        )
        return
    requested_status, record, requested_failure = _validate_requested_attempt(
        document,
        runtime_id=runtime_id,
        requested_route=ROUTES["terra"],
    )
    if requested_status != "accepted":
        _stop_unverified_result(
            output,
            event,
            reason="terra_dispatch_requested_route_unverified",
            failure_class=requested_failure,
            record=record,
        )
        return
    _record_runtime_id(output, runtime_id)
    output["terra_attempt_id"] = event["attempt_id"]
    output["terra_attempt_runtime_id"] = runtime_id
    _set_decision(
        output,
        state=STATE_TERRA_PENDING,
        next_action="await_terra_result",
        reason="terra_dispatch_authorized_once",
        failure_class="NATIVE_ROUTING_FAILURE",
        requested_route=ROUTES["terra"].copy(),
        evidence=_event_evidence(event, record),
    )


def decide(document: Any) -> dict[str, Any]:
    """Validate and replay one route document, returning canonical state data."""

    data = validate_document(document)
    task_packet_hash = data["task_packet_hash"]
    output = _initial_output(task_packet_hash)
    seen_attempt_ids: set[str] = set()

    for index, event in enumerate(data["events"]):
        if output["terminal"]:
            raise _error(f"events[{index}]", "terminal state cannot transition")
        event_name = event["event"]
        if event_name in {"luna_result", "dispatch_terra"}:
            attempt_id = event["attempt_id"]
            if attempt_id in seen_attempt_ids:
                raise _error(f"events[{index}].attempt_id", "must be unique")
            seen_attempt_ids.add(attempt_id)
            output["attempt_ids"].append(attempt_id)

        state = output["state"]
        if state == STATE_PRECHECK:
            if event_name != "precheck":
                raise _error(f"events[{index}].event", "PRECHECK accepts only precheck")
            _precheck(output, data["runtime_records"], event)
        elif state == STATE_LUNA_PENDING:
            if event_name != "luna_result":
                raise _error(f"events[{index}].event", "LUNA_PENDING accepts only luna_result")
            _process_result(output, data["runtime_records"], event, route_name="luna")
        elif state == STATE_FALLBACK_PENDING:
            if event_name != "dispatch_terra":
                raise _error(f"events[{index}].event", "FALLBACK_PENDING accepts only dispatch_terra")
            output["fallback_attempt"] = 1
            _dispatch_terra(output, data["runtime_records"], event)
        elif state == STATE_TERRA_PENDING:
            if event_name != "terra_result":
                raise _error(f"events[{index}].event", "TERRA_PENDING accepts only terra_result")
            _process_result(output, data["runtime_records"], event, route_name="terra")
        else:
            raise _error(f"events[{index}].event", f"state {state} cannot accept events")

    return output


def canonical_json(value: dict[str, Any]) -> str:
    """Serialize a decision with stable key ordering and whitespace."""

    return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def load_document(path: str | Path) -> dict[str, Any]:
    try:
        raw = sys.stdin.buffer.read() if str(path) == "-" else Path(path).read_bytes()
        source = raw.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise _error("document", f"invalid UTF-8 input: {exc}") from exc
    try:
        document = json.loads(source, object_pairs_hook=_reject_duplicate_json_members)
    except json.JSONDecodeError as exc:
        raise _error("document", f"invalid JSON: {exc}") from exc
    return validate_document(document)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay the deterministic native research route")
    subparsers = parser.add_subparsers(dest="command", required=True)
    decide_parser = subparsers.add_parser("decide", help="decide from one route document; use '-' for stdin")
    decide_parser.add_argument("path", nargs="?", default="-")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "decide":
            sys.stdout.write(canonical_json(decide(load_document(args.path))))
            return 0
        raise _error("command", f"unsupported command: {args.command}")
    except (OSError, RouteResearchError, runtime_records.RuntimeRecordError) as exc:
        print(f"route-research error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
