#!/usr/bin/env python3
"""Plan one closed, offline Skill forward step.

This helper deliberately accepts a classified task packet instead of attempting
to classify arbitrary English.  It validates the packet, maps the closed task
kind to the minimum required role, schedules overlapping writers in serial
batches, and adapts an already-produced :mod:`route_research` state into a
single documented-research handoff.  It never spawns, probes, authenticates,
contacts the network, or infers native effective metadata.
"""

from __future__ import annotations

import copy
import importlib.util
import re
from pathlib import Path
from typing import Any


def _load_route_research() -> Any:
    """Load the sibling route helper in CLI and importlib test modes."""

    try:
        import route_research  # type: ignore[import-not-found]

        return route_research
    except ModuleNotFoundError:
        helper_path = Path(__file__).with_name("route_research.py")
        spec = importlib.util.spec_from_file_location("route_research", helper_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"unable to load route helper: {helper_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


route_research = _load_route_research()


SCHEMA_VERSION = 1
TASK_KINDS = frozenset({"simple", "docs", "cuda", "numerical", "security"})
SPECIALISTS = {
    "cuda": "gpu_reviewer",
    "numerical": "numerics_reviewer",
    "security": "security_reviewer",
}
PACKET_FIELDS = {
    "schema_version",
    "task_packet_hash",
    "task_kind",
    "request",
    "files",
    "writers",
    "app_task",
}
APP_TASK_FIELDS = {"requested", "current_request_authorized", "configured_route"}
WRITER_FIELDS = {"writer_id", "files"}
TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ForwardRouteError(ValueError):
    """Raised when a task packet or route-state handoff is not closed."""


def _error(location: str, message: str) -> ForwardRouteError:
    return ForwardRouteError(f"{location}: {message}")


def _check_fields(value: dict[str, Any], allowed: set[str], required: set[str], location: str) -> None:
    extra = [key for key in value if key not in allowed]
    if extra:
        raise _error(location, f"unsupported fields: {sorted(repr(key) for key in extra)}")
    missing = required - set(value)
    if missing:
        raise _error(location, f"missing required fields: {sorted(missing)}")


def _require_string(value: Any, location: str, *, token: bool = False) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _error(location, "must be a non-empty canonical string")
    if any(ord(character) < 0x20 for character in value):
        raise _error(location, "must not contain control characters")
    if token and (value == "unknown" or TOKEN_RE.fullmatch(value) is None):
        raise _error(location, "must be a canonical token")
    return value


def _require_bool(value: Any, location: str) -> bool:
    if type(value) is not bool:
        raise _error(location, "must be boolean")
    return value


def _canonical_string_list(value: Any, location: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list):
        raise _error(location, "must be a list")
    if not allow_empty and not value:
        raise _error(location, "must not be empty")
    result = [_require_string(item, f"{location}[{index}]", token=True) for index, item in enumerate(value)]
    if len(result) != len(set(result)):
        raise _error(location, "must not contain duplicate entries")
    return result

def validate_packet(packet: Any) -> dict[str, Any]:
    """Validate one closed task packet without adding or inferring facts."""

    if not isinstance(packet, dict):
        raise _error("packet", "must be an object")
    _check_fields(packet, PACKET_FIELDS, PACKET_FIELDS, "packet")
    if type(packet["schema_version"]) is not int or packet["schema_version"] != SCHEMA_VERSION:
        raise _error("packet.schema_version", f"must be {SCHEMA_VERSION}")
    task_hash = _require_string(packet["task_packet_hash"], "packet.task_packet_hash")
    if HASH_RE.fullmatch(task_hash) is None:
        raise _error("packet.task_packet_hash", "must be sha256:<64 lowercase hex digits>")
    task_kind = _require_string(packet["task_kind"], "packet.task_kind", token=True)
    if task_kind not in TASK_KINDS:
        raise _error("packet.task_kind", f"unsupported task kind: {task_kind}")
    _require_string(packet["request"], "packet.request")
    _canonical_string_list(packet["files"], "packet.files")

    writers = packet["writers"]
    if not isinstance(writers, list):
        raise _error("packet.writers", "must be a list")
    writer_ids: set[str] = set()
    for index, writer in enumerate(writers):
        location = f"packet.writers[{index}]"
        if not isinstance(writer, dict):
            raise _error(location, "must be an object")
        _check_fields(writer, WRITER_FIELDS, WRITER_FIELDS, location)
        writer_id = _require_string(writer["writer_id"], f"{location}.writer_id", token=True)
        if writer_id in writer_ids:
            raise _error(f"{location}.writer_id", "must be unique")
        writer_ids.add(writer_id)
        _canonical_string_list(writer["files"], f"{location}.files", allow_empty=False)

    app_task = packet["app_task"]
    if not isinstance(app_task, dict):
        raise _error("packet.app_task", "must be an object")
    _check_fields(app_task, APP_TASK_FIELDS, APP_TASK_FIELDS, "packet.app_task")
    requested = _require_bool(app_task["requested"], "packet.app_task.requested")
    authorized = _require_bool(
        app_task["current_request_authorized"],
        "packet.app_task.current_request_authorized",
    )
    _require_string(app_task["configured_route"], "packet.app_task.configured_route")
    if not requested and authorized:
        raise _error(
            "packet.app_task.current_request_authorized",
            "cannot be true when no App task was requested",
        )
    return packet


def _writer_batches(writers: list[dict[str, Any]]) -> list[list[str]]:
    """Serialize only writers that overlap; keep disjoint writers parallel."""

    last_batch_by_file: dict[str, int] = {}
    batches: list[list[str]] = []
    for writer in writers:
        files = writer["files"]
        batch = max(
            (last_batch_by_file[file_name] + 1 for file_name in files if file_name in last_batch_by_file),
            default=0,
        )
        while len(batches) <= batch:
            batches.append([])
        batches[batch].append(writer["writer_id"])
        for file_name in files:
            last_batch_by_file[file_name] = batch
    return batches


def plan_forward(packet: Any) -> dict[str, Any]:
    """Return the minimum deterministic forward plan for a classified packet."""

    data = validate_packet(packet)
    task_kind = data["task_kind"]
    selected_agents: list[str]
    next_action: str
    requested_route: dict[str, str] | None = None
    fallback_policy: dict[str, Any] | None = None

    if task_kind == "simple":
        selected_agents = []
        next_action = "implement_directly"
    elif task_kind == "docs":
        selected_agents = [route_research.ROUTES["luna"]["agent_type"]]
        next_action = "precheck"
        requested_route = {"route": "luna", **copy.deepcopy(route_research.ROUTES["luna"])}
        fallback_policy = {
            "route": "terra",
            "requested_route": {"route": "terra", **copy.deepcopy(route_research.ROUTES["terra"])},
            "permitted_failure_class": "NATIVE_ROUTING_FAILURE",
            "max_attempts": 1,
            "same_task_packet_hash": True,
        }
    else:
        selected_agents = [SPECIALISTS[task_kind]]
        next_action = "run_required_specialist"

    app_task = data["app_task"]
    if not app_task["requested"]:
        app_decision = {
            "requested": False,
            "allowed": False,
            "next_action": "none",
            "reason": "no_app_task_requested",
        }
    elif app_task["current_request_authorized"]:
        app_decision = {
            "requested": True,
            "allowed": True,
            "next_action": "create_app_task",
            "reason": "explicit_current_request_authorization",
        }
    else:
        app_decision = {
            "requested": True,
            "allowed": False,
            "next_action": "stop_unverified",
            "reason": "app_task_requires_explicit_current_request_authorization",
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "task_packet_hash": data["task_packet_hash"],
        "task_kind": task_kind,
        "selected_agents": selected_agents,
        "next_action": next_action,
        "requested_route": requested_route,
        "fallback_policy": fallback_policy,
        "writer_batches": _writer_batches(data["writers"]),
        "app_task": app_decision,
        "native_effective_route": None,
    }


def forward_route(packet: Any, route_state: Any) -> dict[str, Any]:
    """Apply an existing route-helper state to a docs forward plan.

    The route helper owns evidence classification.  This adapter only permits
    the already-classified ``FALLBACK_PENDING`` state to select one Terra
    attempt and otherwise preserves terminal/no-fallback states.
    """

    plan = plan_forward(packet)
    if plan["task_kind"] != "docs":
        raise _error("route_state", "route handoff is only valid for docs tasks")
    if not isinstance(route_state, dict):
        raise _error("route_state", "must be an object")
    if route_state.get("task_packet_hash") != plan["task_packet_hash"]:
        raise _error("route_state.task_packet_hash", "must equal the task packet hash")
    state = route_state.get("state")
    if state not in route_research.TERMINAL_STATES | {route_research.STATE_FALLBACK_PENDING}:
        raise _error("route_state.state", "must be terminal or FALLBACK_PENDING")

    result = copy.deepcopy(plan)
    result["handoff"] = None
    result["fallback_attempt"] = route_state.get("fallback_attempt")
    result["route_state"] = state
    if state == route_research.STATE_FALLBACK_PENDING:
        if route_state.get("failure_class") != "NATIVE_ROUTING_FAILURE":
            raise _error("route_state.failure_class", "FALLBACK_PENDING requires NATIVE_ROUTING_FAILURE")
        if route_state.get("fallback_attempt") != 1:
            raise _error("route_state.fallback_attempt", "FALLBACK_PENDING requires exactly one attempt")
        result["selected_agents"] = [route_research.ROUTES["terra"]["agent_type"]]
        result["next_action"] = "spawn_terra"
        result["handoff"] = {
            "route": "terra",
            "requested_route": {"route": "terra", **copy.deepcopy(route_research.ROUTES["terra"])},
            "task_packet_hash": plan["task_packet_hash"],
            "fallback_attempt": 1,
        }
        return result

    result["selected_agents"] = []
    result["next_action"] = "none"
    return result
