#!/usr/bin/env python3
"""Validate and query independent Versatile Dev runtime records.

Schema version 1 deliberately keeps CLI binaries, App-bundled CLIs, native
spawn attempts, and user-visible App tasks in separate records.  A detector
record is capability/diagnostic evidence only; it is never an observation of a
native spawn or an App task.  The only public operations are ``detect`` (the
two CLI probes used by ``detect-runtime.sh``), ``validate``, and ``query``.

Required record fields:

``schema_version``
    Integer schema version, currently ``1``.
``runtime_id``
    Stable identifier bound to the interface kind, binary path, and version.
``binary_path`` / ``version``
    Binary identity.  Non-binary interfaces use an explicit empty path and
    ``unknown`` version.
``interface_kind``
    One of ``cli_binary``, ``app_bundled_cli``, ``native_spawn_attempt``, or
    ``app_task``.
``multi_agent_generation``
    One of ``none``, ``v1``, ``v2``, or ``unknown``.
``exposed_agent_types``
    A list, or the explicit value ``unknown``.  Detector records use an empty
    list because a CLI capability probe is not native exposure evidence.
``model_support`` / ``effort_support``
    Model slugs and a model-to-efforts mapping, or explicit ``unknown``.
``evidence_source``
    An object with ``kind``, ``runtime_id``, and ``scope``.  The kind must be
    known, the runtime ID must equal this record ID, and scope must be
    ``single-runtime``.
``captured_at`` / ``diagnostic_only``
    Capture timestamp and whether the record is diagnostic-only evidence.

Optional native/App-task observations live inside that same record under
``observed``. Plain ``agent_type``/``model``/``effort`` values are requested or
non-effective observations. Native effective queries require the exact
``effective_agent_type``/``effective_model``/``effective_effort`` fields from a
single ``native_spawn_attempt`` record. The query operation always selects one
``runtime_id`` before checking facts, so it cannot assemble a route from
complementary records.
No routing state transitions are implemented here.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
REQUIRED_FIELDS = (
    "schema_version",
    "runtime_id",
    "binary_path",
    "version",
    "interface_kind",
    "multi_agent_generation",
    "exposed_agent_types",
    "model_support",
    "effort_support",
    "evidence_source",
    "captured_at",
    "diagnostic_only",
)
INTERFACE_KINDS = {
    "cli_binary",
    "app_bundled_cli",
    "native_spawn_attempt",
    "app_task",
}
PROBE_KINDS = {"cli_binary", "app_bundled_cli"}
GENERATION_VALUES = {"none", "v1", "v2", "unknown"}
UNKNOWN = "unknown"
EVIDENCE_SOURCE_KINDS = {
    "detector_probe",
    "fixture",
    "native_spawn_details",
    "app_task_details",
}
EVIDENCE_SOURCE_FIELDS = {"kind", "runtime_id", "scope"}
OBSERVED_KEYS = {
    "agent_type",
    "model",
    "effort",
    "effective_agent_type",
    "effective_model",
    "effective_effort",
}
INTERFACE_ORDER = {
    "cli_binary": 0,
    "app_bundled_cli": 1,
    "native_spawn_attempt": 2,
    "app_task": 3,
}


class RuntimeRecordError(ValueError):
    """Raised for malformed, ambiguous, or unsafe runtime evidence."""


def _fail(location: str, message: str) -> RuntimeRecordError:
    return RuntimeRecordError(f"{location}: {message}")


def _require_string(value: Any, location: str, *, allow_empty: bool = False) -> None:
    if not isinstance(value, str):
        raise _fail(location, "must be a string")
    if not allow_empty and not value.strip():
        raise _fail(location, "must not be empty")


def _validate_string_list(value: Any, location: str) -> None:
    if value == UNKNOWN:
        return
    if not isinstance(value, list):
        raise _fail(location, "must be a list or 'unknown'")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise _fail(location, "must contain non-empty strings")
    if UNKNOWN in value:
        raise _fail(location, "must not mix 'unknown' with known values")
    if len(value) != len(set(value)):
        raise _fail(location, "contains duplicate values")


def _validate_evidence_source(value: Any, location: str, runtime_id: str) -> None:
    if not isinstance(value, dict):
        raise _fail(location, "must be a strict single-runtime object")
    if "runtime_ids" in value:
        raise _fail(location, "must use exactly one runtime_id, not runtime_ids")
    missing = EVIDENCE_SOURCE_FIELDS - set(value)
    extra = set(value) - EVIDENCE_SOURCE_FIELDS
    if missing:
        raise _fail(location, f"missing required provenance fields: {sorted(missing)}")
    if extra:
        raise _fail(location, f"unsupported provenance fields: {sorted(extra)}")
    _require_string(value["kind"], f"{location}.kind")
    if value["kind"] not in EVIDENCE_SOURCE_KINDS:
        raise _fail(location, "unsupported provenance kind: " + str(value["kind"]))
    _require_string(value["runtime_id"], f"{location}.runtime_id")
    if value["runtime_id"] != runtime_id:
        raise _fail(location, "provenance runtime_id does not match record runtime_id")
    if value["scope"] != "single-runtime":
        raise _fail(location, "provenance scope must be single-runtime")


def _validate_observed(record: dict[str, Any], location: str) -> None:
    observed = record.get("observed")
    if observed is None:
        return
    if record["interface_kind"] in PROBE_KINDS:
        raise _fail(location, "CLI/App-bundled CLI probes may not contain observations")
    if not isinstance(observed, dict):
        raise _fail(location, "must be an object")
    unknown_keys = set(observed) - OBSERVED_KEYS
    if unknown_keys:
        raise _fail(location, f"unsupported keys: {sorted(unknown_keys)}")
    for key, value in observed.items():
        _require_string(value, f"{location}.{key}", allow_empty=False)
    for plain, effective in (
        ("agent_type", "effective_agent_type"),
        ("model", "effective_model"),
        ("effort", "effective_effort"),
    ):
        if plain in observed and effective in observed:
            if observed[plain] != UNKNOWN and observed[effective] != UNKNOWN and observed[plain] != observed[effective]:
                raise _fail(location, f"conflicting {plain} and {effective}")
    if record["interface_kind"] == "app_task":
        effective_keys = set(observed) & {"effective_agent_type", "effective_model", "effective_effort"}
        if effective_keys:
            raise _fail(location, "App-task evidence may not populate native effective fields")


def validate_record(record: Any, index: int = 0) -> dict[str, Any]:
    location = f"records[{index}]"
    if not isinstance(record, dict):
        raise _fail(location, "must be an object")
    missing = [field for field in REQUIRED_FIELDS if field not in record]
    if missing:
        raise _fail(location, f"missing required fields: {missing}")

    if record["schema_version"] != SCHEMA_VERSION:
        raise _fail(location, f"schema_version must be {SCHEMA_VERSION}")
    _require_string(record["runtime_id"], f"{location}.runtime_id")
    _require_string(record["binary_path"], f"{location}.binary_path", allow_empty=True)
    _require_string(record["version"], f"{location}.version")
    _require_string(record["interface_kind"], f"{location}.interface_kind")
    if record["interface_kind"] not in INTERFACE_KINDS:
        raise _fail(location, f"unsupported interface_kind: {record['interface_kind']}")
    if record["multi_agent_generation"] not in GENERATION_VALUES:
        raise _fail(location, "invalid multi_agent_generation")
    _validate_string_list(record["exposed_agent_types"], f"{location}.exposed_agent_types")
    _validate_string_list(record["model_support"], f"{location}.model_support")

    efforts = record["effort_support"]
    if efforts == UNKNOWN:
        pass
    elif not isinstance(efforts, dict):
        raise _fail(f"{location}.effort_support", "must be an object or 'unknown'")
    else:
        if record["model_support"] == UNKNOWN:
            raise _fail(
                f"{location}.effort_support",
                "known effort support requires known model_support",
            )
        for model, values in efforts.items():
            _require_string(model, f"{location}.effort_support key")
            _validate_string_list(values, f"{location}.effort_support[{model!r}]")
        if isinstance(record["model_support"], list):
            extra_models = sorted(set(efforts) - set(record["model_support"]))
            if extra_models:
                raise _fail(
                    f"{location}.effort_support",
                    f"contains models absent from model_support: {extra_models}",
                )

    _validate_evidence_source(record["evidence_source"], f"{location}.evidence_source", record["runtime_id"])
    _require_string(record["captured_at"], f"{location}.captured_at")
    if record["captured_at"] != UNKNOWN:
        try:
            timestamp = dt.datetime.fromisoformat(record["captured_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise _fail(f"{location}.captured_at", "must be an ISO-8601 timestamp or 'unknown'") from exc
        if timestamp.tzinfo is None:
            raise _fail(f"{location}.captured_at", "must include a timezone")
    if not isinstance(record["diagnostic_only"], bool):
        raise _fail(f"{location}.diagnostic_only", "must be boolean")
    if record["interface_kind"] in PROBE_KINDS and not record["diagnostic_only"]:
        raise _fail(location, "CLI/App-bundled CLI probe records must be diagnostic_only=true")
    if record["interface_kind"] in {"native_spawn_attempt", "app_task"} and record["binary_path"] not in {"", UNKNOWN}:
        raise _fail(location, "non-binary interfaces require an explicit empty/unknown binary_path")
    _validate_observed(record, location)
    return record


def validate_document(document: Any) -> dict[str, Any]:
    """Validate a versioned record document and reject duplicate provenance."""

    if not isinstance(document, dict):
        raise RuntimeRecordError("document: must be an object")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeRecordError(f"document.schema_version must be {SCHEMA_VERSION}")
    records = document.get("records")
    if not isinstance(records, list):
        raise RuntimeRecordError("document.records: must be a list")
    seen: set[str] = set()
    for index, record in enumerate(records):
        validate_record(record, index)
        runtime_id = record["runtime_id"]
        if runtime_id in seen:
            raise _fail(f"records[{index}].runtime_id", f"duplicate runtime_id: {runtime_id}")
        seen.add(runtime_id)

    assertions = document.get("diagnostic_assertions", {})
    if not isinstance(assertions, dict):
        raise RuntimeRecordError("document.diagnostic_assertions: must be an object")
    for name, assertion in assertions.items():
        if isinstance(assertion, dict):
            if assertion.get("diagnostic_only") is not True:
                raise _fail(f"diagnostic_assertions.{name}", "must be diagnostic_only=true")
            value = assertion.get("value")
        else:
            value = assertion
        if name == "native_v2_luna" and value not in {"yes", "no", UNKNOWN}:
            raise _fail(f"diagnostic_assertions.{name}", "must be yes, no, or unknown")
    return document


def _ordered_document(document: dict[str, Any]) -> dict[str, Any]:
    ordered = copy.deepcopy(document)
    ordered["records"] = sorted(
        ordered["records"],
        key=lambda item: (INTERFACE_ORDER.get(item["interface_kind"], 99), item["runtime_id"]),
    )
    for record in ordered["records"]:
        if isinstance(record.get("exposed_agent_types"), list):
            record["exposed_agent_types"] = sorted(record["exposed_agent_types"])
        if isinstance(record.get("model_support"), list):
            record["model_support"] = sorted(record["model_support"])
        if isinstance(record.get("effort_support"), dict):
            record["effort_support"] = {
                model: sorted(values) if isinstance(values, list) else values
                for model, values in sorted(record["effort_support"].items())
            }
    return ordered


def canonical_json(document: dict[str, Any]) -> str:
    """Return deterministic JSON; capture timestamps remain intentionally live."""

    validate_document(document)
    return json.dumps(_ordered_document(document), indent=2, sort_keys=True) + "\n"


def load_document(path: str | Path) -> dict[str, Any]:
    source = sys.stdin.read() if str(path) == "-" else Path(path).read_text(encoding="utf-8")
    try:
        document = json.loads(source)
    except json.JSONDecodeError as exc:
        raise RuntimeRecordError(f"invalid JSON: {exc}") from exc
    return validate_document(document)


def query_record(
    document: dict[str, Any],
    *,
    runtime_id: str | None = None,
    interface_kind: str | None = None,
    require_generation: str | None = None,
    require_agent_types: Iterable[str] = (),
    require_models: Iterable[str] = (),
    require_efforts: Iterable[str] = (),
    require_effective_agent_type: str | None = None,
    require_effective_model: str | None = None,
    require_effective_effort: str | None = None,
) -> dict[str, Any]:
    """Return facts from exactly one record, failing closed on ambiguity."""

    validate_document(document)
    records = document["records"]
    if runtime_id is None:
        if len(records) != 1:
            raise RuntimeRecordError(
                "refusing cross-runtime fact assembly: --runtime-id is required when multiple records exist"
            )
        selected = records[0]
    else:
        matches = [record for record in records if record["runtime_id"] == runtime_id]
        if len(matches) != 1:
            raise RuntimeRecordError(f"runtime_id must select exactly one record: {runtime_id}")
        selected = matches[0]
    if interface_kind is not None and selected["interface_kind"] != interface_kind:
        raise RuntimeRecordError(
            f"runtime_id {selected['runtime_id']} has interface_kind {selected['interface_kind']}, not {interface_kind}"
        )

    if require_generation is not None:
        if selected["multi_agent_generation"] == UNKNOWN:
            raise RuntimeRecordError("required multi_agent_generation is unknown")
        if selected["multi_agent_generation"] != require_generation:
            raise RuntimeRecordError("required multi_agent_generation is not present in the selected record")

    for agent_type in require_agent_types:
        exposed = selected["exposed_agent_types"]
        if exposed == UNKNOWN or agent_type not in exposed:
            raise RuntimeRecordError(f"required exposed agent type is absent/unknown: {agent_type}")

    for model in require_models:
        supported = selected["model_support"]
        if supported == UNKNOWN or model not in supported:
            raise RuntimeRecordError(f"required model support is absent/unknown: {model}")

    models = selected["model_support"]
    efforts = selected["effort_support"]
    for requirement in require_efforts:
        if ":" not in requirement:
            raise RuntimeRecordError(f"effort requirement must be MODEL:EFFORT: {requirement}")
        model, effort = requirement.split(":", 1)
        if models == UNKNOWN or model not in models:
            raise RuntimeRecordError(f"required model support is absent/unknown: {model}")
        if efforts == UNKNOWN or model not in efforts or efforts[model] == UNKNOWN or effort not in efforts[model]:
            raise RuntimeRecordError(f"required effort support is absent/unknown: {requirement}")

    observed = selected.get("observed", {})
    for key, required in (
        ("agent_type", require_effective_agent_type),
        ("model", require_effective_model),
        ("effort", require_effective_effort),
    ):
        if required is None:
            continue
        if selected["interface_kind"] != "native_spawn_attempt":
            raise RuntimeRecordError(
                "native effective "
                + key
                + " is unavailable for interface "
                + selected["interface_kind"]
                + "; STOP_UNVERIFIED"
            )
        field = f"effective_{key}"
        actual = observed.get(field)
        if actual in (None, "", UNKNOWN):
            raise RuntimeRecordError(f"required native effective {field} is absent/unknown; STOP_UNVERIFIED")
        if actual != required:
            raise RuntimeRecordError(f"required native effective {field} does not match selected record")

    return {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": selected["runtime_id"],
        "interface_kind": selected["interface_kind"],
        "record": _ordered_document({"schema_version": SCHEMA_VERSION, "records": [selected]})["records"][0],
    }


def _run_probe(binary_path: str, *arguments: str) -> str:
    if not binary_path or not os.access(binary_path, os.X_OK):
        return ""
    try:
        result = subprocess.run(
            [binary_path, *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout if result.returncode == 0 else ""


def _parse_features(text: str) -> dict[str, bool]:
    values: dict[str, bool] = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0] in {"multi_agent", "multi_agent_v2"}:
            if fields[2] == "true":
                values[fields[0]] = True
            elif fields[2] == "false":
                values[fields[0]] = False
    return values


def _generation(features: dict[str, bool]) -> str:
    if features.get("multi_agent_v2") is True:
        return "v2"
    if features.get("multi_agent") is True:
        return "v1"
    if features.get("multi_agent") is False and features.get("multi_agent_v2") is False:
        return "none"
    return UNKNOWN


def _parse_models(text: str) -> tuple[list[str] | str, dict[str, list[str] | str] | str]:
    if not text:
        return UNKNOWN, UNKNOWN
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return UNKNOWN, UNKNOWN
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return UNKNOWN, UNKNOWN
    model_support: list[str] = []
    effort_support: dict[str, list[str] | str] = {}
    for model in models:
        if not isinstance(model, dict) or not isinstance(model.get("slug"), str) or not model["slug"].strip():
            continue
        slug = model["slug"]
        model_support.append(slug)
        levels = model.get("supported_reasoning_levels")
        if not isinstance(levels, list):
            effort_support[slug] = UNKNOWN
            continue
        effort_support[slug] = sorted(
            {
                item["effort"]
                for item in levels
                if isinstance(item, dict) and isinstance(item.get("effort"), str) and item["effort"].strip()
            }
        )
    model_support = sorted(set(model_support))
    return model_support, {key: effort_support[key] for key in sorted(effort_support)}


def _runtime_id(interface_kind: str, binary_path: str, version: str) -> str:
    identity = json.dumps([interface_kind, binary_path, version], separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    return f"{interface_kind}:{digest}"


def _capture_time() -> str:
    # The installer persists the probe document and compares it byte-for-byte
    # on reinstall.  An offline detector therefore records an explicit unknown
    # capture time rather than manufacturing a changing value; supplied native
    # and App-task records may carry a real ISO-8601 timestamp.
    return UNKNOWN


def _probe_record(interface_kind: str, binary_path: str, captured_at: str) -> dict[str, Any]:
    version_lines = [line.strip() for line in _run_probe(binary_path, "--version").splitlines() if line.strip()]
    version = version_lines[-1] if version_lines else UNKNOWN
    features = _parse_features(_run_probe(binary_path, "features", "list"))
    model_support, effort_support = _parse_models(_run_probe(binary_path, "debug", "models", "--bundled"))
    runtime_id = _runtime_id(interface_kind, binary_path, version)
    return {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": runtime_id,
        "binary_path": binary_path,
        "version": version,
        "interface_kind": interface_kind,
        "multi_agent_generation": _generation(features),
        "exposed_agent_types": [],
        "model_support": model_support,
        "effort_support": effort_support,
        "evidence_source": {
            "kind": "detector_probe",
            "runtime_id": runtime_id,
            "scope": "single-runtime",
        },
        "captured_at": captured_at,
        "diagnostic_only": True,
    }


def detect_document(codex_bin: str, app_codex_bin: str, native_v2_luna: str) -> dict[str, Any]:
    """Probe only the CLI and App-bundled CLI, never native/App-task interfaces."""

    captured_at = _capture_time()
    records = [
        _probe_record("cli_binary", codex_bin, captured_at),
        _probe_record("app_bundled_cli", app_codex_bin, captured_at),
    ]
    document = {
        "schema_version": SCHEMA_VERSION,
        "records": records,
        "diagnostic_assertions": {
            "native_v2_luna": {
                "value": native_v2_luna,
                "evidence_source": {
                    "kind": "argument_assertion",
                    "scope": "diagnostic-only",
                },
                "diagnostic_only": True,
            }
        },
    }
    return validate_document(document)


def _supports(record: dict[str, Any], model: str, effort: str) -> bool:
    models = record["model_support"]
    efforts = record["effort_support"]
    return (
        isinstance(models, list)
        and model in models
        and isinstance(efforts, dict)
        and isinstance(efforts.get(model), list)
        and effort in efforts[model]
    )


def recommend_profile(records: list[dict[str, Any]]) -> tuple[str, str, str]:
    """Return a diagnostic profile from one probe record, ignoring assertions."""

    ordered = sorted(records, key=lambda item: (INTERFACE_ORDER[item["interface_kind"]], item["runtime_id"]))
    for record in ordered:
        if (
            record["interface_kind"] in PROBE_KINDS
            and record["diagnostic_only"]
            and record["multi_agent_generation"] == "v2"
            and isinstance(record["exposed_agent_types"], list)
            and bool(record["exposed_agent_types"])
            and _supports(record, "gpt-5.6-luna", "max")
        ):
            return (
                "luna-v2",
                record["runtime_id"],
                "Diagnostic only: one V2 probe record independently contains native exposure and Luna/Max capability; native effective routing is unverified.",
            )
    for record in ordered:
        if (
            record["interface_kind"] in PROBE_KINDS
            and record["diagnostic_only"]
            and record["multi_agent_generation"] == "v1"
            and _supports(record, "gpt-5.6-luna", "max")
        ):
            return (
                "luna-v1",
                record["runtime_id"],
                "Diagnostic only: one V1 runtime record contains Luna/Max capability.",
            )
    return (
        "terra-fallback",
        "",
        "Diagnostic only: no single probe record independently verifies native exposure and required capability; fail closed.",
    )


def _legacy_bool(value: bool | None) -> str:
    return UNKNOWN if value is None else ("true" if value else "false")


def _legacy_projection(record: dict[str, Any]) -> dict[str, str]:
    generation = record["multi_agent_generation"]
    models = record["model_support"]
    efforts = record["effort_support"]
    known_models = isinstance(models, list)
    known_efforts = isinstance(efforts, dict)
    has_luna = None if not known_models else "gpt-5.6-luna" in models
    has_luna_max = None if not (known_models and known_efforts and has_luna) else _supports(record, "gpt-5.6-luna", "max")
    if known_models and known_efforts and has_luna and not has_luna_max:
        has_luna_max = False
    return {
        "path": record["binary_path"],
        "version": record["version"],
        "multi_agent": _legacy_bool(None if generation == UNKNOWN else generation in {"v1", "v2"}),
        "multi_agent_v2": _legacy_bool(None if generation == UNKNOWN else generation == "v2"),
        "luna": _legacy_bool(has_luna),
        "luna_max": _legacy_bool(has_luna_max),
    }


def _shell_assignment(name: str, value: str) -> str:
    return f"{name}={shlex.quote(value)}"


def env_output(document: dict[str, Any], native_v2_luna: str) -> str:
    records = {record["interface_kind"]: record for record in document["records"]}
    cli = _legacy_projection(records["cli_binary"])
    app = _legacy_projection(records["app_bundled_cli"])
    profile, runtime_id, reason = recommend_profile(document["records"])
    lines = [
        _shell_assignment("RUNTIME_RECORD_SCHEMA_VERSION", str(SCHEMA_VERSION)),
        _shell_assignment("RUNTIME_RECORDS_JSON", json.dumps(_ordered_document(document), sort_keys=True, separators=(",", ":"))),
    ]
    for prefix, values in (("CLI", cli), ("APP_CODEX", app)):
        for key, value in values.items():
            lines.append(_shell_assignment(f"{prefix}_{key.upper()}", value))
    lines.extend(
        [
            _shell_assignment("NATIVE_V2_LUNA", native_v2_luna),
            _shell_assignment("NATIVE_V2_LUNA_DIAGNOSTIC_ONLY", "true"),
            _shell_assignment("RECOMMENDED_PROFILE", profile),
            _shell_assignment("RECOMMENDED_PROFILE_DIAGNOSTIC_ONLY", "true"),
            _shell_assignment("RECOMMENDATION_RUNTIME_ID", runtime_id),
            _shell_assignment("ROUTE_REASON", reason),
        ]
    )
    return "\n".join(lines) + "\n"


def _default_cli_path() -> str:
    configured = os.environ.get("CODEX_BIN")
    return configured if configured is not None else (shutil.which("codex") or "")


def _default_app_path() -> str:
    return os.environ.get("APP_CODEX_BIN", "/Applications/ChatGPT.app/Contents/Resources/codex")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and query independent Versatile Dev runtime records.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    detect = subparsers.add_parser(
        "detect",
        help="probe only CLI and App-bundled CLI binaries and emit diagnostic records",
    )
    detect.add_argument("--format", choices=("json", "env", "profile"), default="json")
    detect.add_argument("--codex-bin", default=None)
    detect.add_argument("--app-codex-bin", default=None)
    detect.add_argument("--native-v2-luna", choices=("yes", "no", UNKNOWN), default=None)

    validate = subparsers.add_parser("validate", help="validate one record document; use '-' for stdin")
    validate.add_argument("path", nargs="?", default="-")

    query = subparsers.add_parser("query", help="query facts from one runtime_id only; use '-' for stdin")
    query.add_argument("path", nargs="?", default="-")
    query.add_argument("--runtime-id")
    query.add_argument("--interface-kind", choices=sorted(INTERFACE_KINDS))
    query.add_argument("--require-generation")
    query.add_argument("--require-agent-type", action="append", default=[])
    query.add_argument("--require-model", action="append", default=[])
    query.add_argument("--require-effort", action="append", default=[])
    query.add_argument(
        "--require-effective-agent-type",
        "--require-observed-agent-type",
        dest="require_effective_agent_type",
        help="require exact native effective_agent_type metadata",
    )
    query.add_argument(
        "--require-effective-model",
        "--require-observed-model",
        dest="require_effective_model",
        help="require exact native effective_model metadata",
    )
    query.add_argument(
        "--require-effective-effort",
        "--require-observed-effort",
        dest="require_effective_effort",
        help="require exact native effective_effort metadata",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "detect":
            codex_bin = _default_cli_path() if args.codex_bin is None else args.codex_bin
            app_codex_bin = _default_app_path() if args.app_codex_bin is None else args.app_codex_bin
            native_v2_luna = args.native_v2_luna or os.environ.get("VERSATILE_NATIVE_V2_LUNA", UNKNOWN)
            document = detect_document(codex_bin, app_codex_bin, native_v2_luna)
            if args.format == "json":
                sys.stdout.write(canonical_json(document))
            elif args.format == "env":
                sys.stdout.write(env_output(document, native_v2_luna))
            else:
                sys.stdout.write(recommend_profile(document["records"])[0] + "\n")
            return 0
        if args.command == "validate":
            document = load_document(args.path)
            print(f"valid runtime-record document: {len(document['records'])} record(s)")
            return 0
        document = load_document(args.path)
        result = query_record(
            document,
            runtime_id=args.runtime_id,
            interface_kind=args.interface_kind,
            require_generation=args.require_generation,
            require_agent_types=args.require_agent_type,
            require_models=args.require_model,
            require_efforts=args.require_effort,
            require_effective_agent_type=args.require_effective_agent_type,
            require_effective_model=args.require_effective_model,
            require_effective_effort=args.require_effective_effort,
        )
        sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        return 0
    except (OSError, RuntimeRecordError) as exc:
        print(f"runtime-record error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
