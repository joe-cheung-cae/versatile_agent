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

import argparse
import copy
import hashlib
import importlib.util
import json
import posixpath
import re
import sys
import unicodedata
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
WRITABLE_ROLES = frozenset({"implementer", "tester"})
TEST_PATH_PREFIX = "tests/"
TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ForwardRouteError(ValueError):
    """Raised when a task packet or route-state handoff is not closed."""


def _error(location: str, message: str) -> ForwardRouteError:
    return ForwardRouteError(f"{location}: {message}")


def _check_fields(value: dict[str, Any], allowed: set[str], required: set[str], location: str) -> None:
    if any(not isinstance(key, str) for key in value):
        raise _error(location, "member names must be strings")
    extra = [key for key in value if key not in allowed]
    if extra:
        raise _error(location, f"unsupported fields: {sorted(repr(key) for key in extra)}")
    missing = required - set(value)
    if missing:
        raise _error(location, f"missing required fields: {sorted(missing)}")


def _require_string(value: Any, location: str, *, token: bool = False) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _error(location, "must be a non-empty canonical string")
    if any(
        ord(character) < 0x20
        or ord(character) == 0x7F
        or unicodedata.category(character) in {"Cc", "Cf"}
        or character in {"\u2028", "\u2029"}
        for character in value
    ):
        raise _error(location, "must not contain control characters")
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise _error(location, "must not contain unpaired surrogates")
    if token and (value == "unknown" or TOKEN_RE.fullmatch(value) is None):
        raise _error(location, "must be a canonical token")
    return value


def _require_bool(value: Any, location: str) -> bool:
    if type(value) is not bool:
        raise _error(location, "must be boolean")
    return value


def _canonical_repo_path(value: Any, location: str) -> str:
    path = _require_string(value, location)
    if path.startswith("/") or "\\" in path:
        raise _error(location, "must be a relative POSIX path")
    if unicodedata.normalize("NFC", path) != path:
        raise _error(location, "must use canonical Unicode normalization")
    if posixpath.normpath(path) != path:
        raise _error(location, "must not contain normalization aliases")
    segments = path.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise _error(location, "must not contain empty, dot, or dotdot segments")
    return path


def portable_collision_key(path: str) -> str:
    """Return the portable repo-relative identity used for file collisions.

    The key deliberately applies NFC normalization followed by Unicode
    casefolding.  It is conservative for case-insensitive worktrees: paths
    with the same key are treated as aliases even when a case-sensitive host
    would keep them distinct.
    """

    return unicodedata.normalize("NFC", path).casefold()


def _canonical_path_list(value: Any, location: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list):
        raise _error(location, "must be a list")
    if not allow_empty and not value:
        raise _error(location, "must not be empty")
    result = [_canonical_repo_path(item, f"{location}[{index}]") for index, item in enumerate(value)]
    collision_keys = [portable_collision_key(path) for path in result]
    if len(collision_keys) != len(set(collision_keys)):
        raise _error(location, "must not contain portable path aliases (NFC+casefold collision key)")
    return result


def _validate_packet_shape(packet: Any) -> dict[str, Any]:
    """Validate packet structure and return a defensive copy before hash checking."""

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
    packet_files = _canonical_path_list(packet["files"], "packet.files")
    packet_file_set = set(packet_files)
    packet_file_keys = {portable_collision_key(path) for path in packet_files}

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
        if writer_id not in WRITABLE_ROLES:
            raise _error(f"{location}.writer_id", "is not a writable forward role")
        writer_ids.add(writer_id)
        writer_files = _canonical_path_list(writer["files"], f"{location}.files", allow_empty=False)
        writer_file_keys = {portable_collision_key(path) for path in writer_files}
        if not writer_file_keys.issubset(packet_file_keys):
            raise _error(f"{location}.files", "must be members of packet.files by portable collision key")
        if not set(writer_files).issubset(packet_file_set):
            raise _error(f"{location}.files", "must be exact canonical members of packet.files")
        if writer_id == "tester" and any(
            not path.startswith(TEST_PATH_PREFIX) for path in writer_files
        ):
            raise _error(f"{location}.files", "tester ownership is limited to tests/")

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
    return copy.deepcopy(packet)


def _canonical_packet_json_from_validated(packet: dict[str, Any]) -> str:
    content = copy.deepcopy(packet)
    content.pop("task_packet_hash")
    return json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_packet_json(packet: Any) -> str:
    """Return canonical packet JSON with the claimed hash member excluded."""

    return _canonical_packet_json_from_validated(_validate_packet_shape(packet))


def canonical_packet_hash(packet: Any) -> str:
    """Return the deterministic SHA-256 hash of canonical packet content."""

    encoded = canonical_packet_json(packet).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def validate_packet(packet: Any) -> dict[str, Any]:
    """Validate one closed task packet, including its claimed canonical hash."""

    validated = _validate_packet_shape(packet)
    if validated["task_packet_hash"] != _canonical_packet_hash_from_validated(validated):
        raise _error("packet.task_packet_hash", "does not match canonical packet content")
    return copy.deepcopy(validated)


def _canonical_packet_hash_from_validated(packet: dict[str, Any]) -> str:
    encoded = _canonical_packet_json_from_validated(packet).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _writer_batches(writers: list[dict[str, Any]]) -> list[list[str]]:
    """Serialize only writers that overlap; keep disjoint writers parallel."""

    last_batch_by_file: dict[str, int] = {}
    batches: list[list[str]] = []
    for writer in writers:
        files = writer["files"]
        collision_keys = [portable_collision_key(file_name) for file_name in files]
        batch = max(
            (
                last_batch_by_file[collision_key] + 1
                for collision_key in collision_keys
                if collision_key in last_batch_by_file
            ),
            default=0,
        )
        while len(batches) <= batch:
            batches.append([])
        batches[batch].append(writer["writer_id"])
        for collision_key in collision_keys:
            last_batch_by_file[collision_key] = batch
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


def _reject_json_constant(value: str) -> None:
    raise ForwardRouteError("non-finite JSON numbers are not allowed")


def _reject_duplicate_json_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ForwardRouteError("duplicate JSON member")
        result[key] = value
    return result


def load_json(path: str | Path) -> Any:
    """Load strict UTF-8 JSON with duplicate-member rejection."""

    try:
        raw = sys.stdin.buffer.read() if str(path) == "-" else Path(path).read_bytes()
        source = raw.decode("utf-8", errors="strict")
        return json.loads(
            source,
            object_pairs_hook=_reject_duplicate_json_members,
            parse_constant=_reject_json_constant,
        )
    except UnicodeDecodeError as exc:
        raise _error("input", "invalid UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise _error("input", "invalid JSON") from exc


def _replay_route_document(route_document: Any, task_packet_hash: str) -> dict[str, Any]:
    if not isinstance(route_document, dict):
        raise _error("route_document", "must be the full route document object")
    if set(route_document) != route_research.TOP_LEVEL_FIELDS:
        raise _error("route_document", "must contain the full closed route-document schema")
    if route_document.get("task_packet_hash") != task_packet_hash:
        raise _error("route_document.task_packet_hash", "must equal the packet hash")
    try:
        state = route_research.decide(copy.deepcopy(route_document))
    except (route_research.RouteResearchError, route_research.runtime_records.RuntimeRecordError) as exc:
        raise _error("route_document", "failed closed route replay") from exc
    if state.get("task_packet_hash") != task_packet_hash:
        raise _error("route_document.task_packet_hash", "replay returned a mismatched packet hash")
    return state


def forward_route(packet: Any, route_document: Any) -> dict[str, Any]:
    """Replay a full route document and adapt its closed state to a forward plan.

    The route helper owns evidence classification.  This adapter never accepts
    a caller-built summary state; it only permits the replayed
    ``FALLBACK_PENDING`` state to select one Terra attempt and otherwise
    preserves terminal/no-fallback states.
    """

    validated_packet = validate_packet(packet)
    plan = plan_forward(validated_packet)
    if plan["task_kind"] != "docs":
        raise _error("route_document", "route handoff is only valid for docs tasks")
    route_state = _replay_route_document(route_document, plan["task_packet_hash"])
    state = route_state.get("state")
    if state not in route_research.TERMINAL_STATES | {route_research.STATE_FALLBACK_PENDING}:
        raise _error("route_document.state", "must be terminal or FALLBACK_PENDING")

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


def canonical_json(value: Any) -> str:
    """Serialize one CLI result with stable ordering and no non-finite values."""

    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan and replay the closed offline Skill forward contract")
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="plan one classified packet; use '-' for stdin")
    plan_parser.add_argument("packet", nargs="?", default="-")
    replay_parser = subparsers.add_parser(
        "replay",
        help="replay one full route document for one packet",
    )
    replay_parser.add_argument("packet")
    replay_parser.add_argument("route_document")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "plan":
            result = plan_forward(load_json(args.packet))
        elif args.command == "replay":
            result = forward_route(load_json(args.packet), load_json(args.route_document))
        else:
            raise _error("command", "unsupported command")
        sys.stdout.write(canonical_json(result))
        return 0
    except (OSError, ForwardRouteError) as exc:
        print(f"forward-router error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
