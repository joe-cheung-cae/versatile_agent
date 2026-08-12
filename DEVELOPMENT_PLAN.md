# Versatile Agent implementation and acceptance record

This document records the current shipped implementation and its acceptance
boundaries. The dual-researcher bundle, deterministic helper, and historical
installer migration described below are shipped behavior; the remaining live
boundary is optional schema review rather than a claimed conformance result.

## Implemented bundle

The bundle contains 13 unique common agents under
`payload/agents/common/`:

```text
code_mapper
architect
implementer
tester
test_validator
reviewer
gpu_reviewer
numerics_reviewer
parallelism_reviewer
performance_profiler
security_reviewer
docs_researcher_luna
docs_researcher_terra
```

The two documentation researchers are simultaneous, distinct named profiles:

| File | Requested model/effort | Sandbox |
| --- | --- | --- |
| `payload/agents/common/docs_researcher_luna.toml` | `gpt-5.6-luna` / `max` | `read-only` |
| `payload/agents/common/docs_researcher_terra.toml` | `gpt-5.6-terra` / `high` | `read-only` |

There is no current source profile named `docs_researcher.toml`. The installer
recognizes that path only as a historical compatibility payload: a normal
install backs it up and removes it before installing the two distinct files;
`--check` reports migration pending, `--dry-run` reports the intended migration,
and customized, symlink, or directory conflicts are preserved and fail closed.

## Current architecture and authority boundaries

```mermaid
flowchart TB
    U["Current user request"] --> L["versatile-dev Skill / lead"]
    L --> P["Closed classified task packet"]
    P --> F["forward_router.py"]
    F --> R["route_research.py replay"]
    R --> C{"Docs route state"}
    C -->|"Luna first"| LU["docs_researcher_luna\ngpt-5.6-luna / max"]
    C -->|"NATIVE_ROUTING_FAILURE + same packet hash"| TE["At most one docs_researcher_terra\ngpt-5.6-terra / high"]
    C -->|"other failure or unknown evidence"| S["STOP_FAILED / STOP_UNVERIFIED"]
    LU --> A["Parent Skill verifies and accepts"]
    TE --> A
    S --> A
    L --> AP["Optional App user-visible task\nexplicit current-request authorization"]
    AP --> AX["App facts remain separate"]
    I["install.sh"] --> M["installation_manifest\ninstalled/configured facts"]
    D["runtime_records.py\nCLI/App diagnostic records"] --> DR["Diagnostic runtime records\nseparate artifact"]
    N["Native or App attempt"] --> RA["runtime_audit.py\nper-attempt audit"]
    M -. "never supplies effective route" .-> A
    RA -. "same-attempt observed evidence only" .-> A
```

The parent Skill owns classification, native/App actions, diff/test/review
triage, and acceptance. `forward_router.py` and `route_research.py` are
deterministic offline helpers: they consume closed inputs, validate canonical
hashes and state, and never classify prose, spawn, probe, authenticate, access
the network, or invent native effective metadata.

For a documentation task, the same-interface PRECHECK must expose both
researcher names before Luna is requested. Exactly one Terra attempt is allowed
only after a classified native routing rejection or a complete same-attempt
native mismatch, and it must carry the same canonical `task_packet_hash`.
Content, tool, and task failures are terminal `STOP_FAILED`; a timeout is
`STOP_FAILED` only when route metadata is complete and non-conflicting.
Missing, conflicting, unobservable, and unknown route evidence is
`STOP_UNVERIFIED`. No other outcome authorizes Terra.

The App user-visible task lane is independent of native subagents and native
fallback. It requires explicit authorization in the current request. The
`gpt-5.6-luna` / `max` App lane used by this P3 development session is not
repository/native effective-route evidence.

## Installation and compatibility record

`install.sh` supports project and user/global scopes. It installs:

- `.agents/skills/versatile-dev` for the Skill;
- `.codex/agents/*.toml` or the corresponding user Codex agents directory for
  all 13 common agents;
- a schema-v2 `.codex/versatile-agent/install-manifest.json` (or the user
  equivalent); and
- an optional idempotent `AGENTS.md` activation snippet.

The accepted selectors are `auto`, `luna-v1`, `luna-v2`, and
`terra-fallback`. `auto` probes the selected CLI and App-bundled CLI and
converts diagnostic output into a compatibility selector. The legacy selector
names remain supported for existing install commands and manifests, but every
successful installation contains both distinct researcher files. The manifest
records `selected_profile`, installed identities, and configured researcher
pins; none of those facts proves the route used by a task.

The installer also preserves unrelated TOML, creates recoverable backups before
replacement, supports `--check` and `--dry-run`, and migrates only recognized
historical researcher payloads. Unknown or conflicting legacy paths are not
overwritten.

## Evidence and artifact separation

The installation manifest is a closed configuration artifact. It records the
bundle version, scope, selected legacy selector, 13 installed identities, and
the configured Luna/Terra researcher tuples. It does not record probe,
capability, observed, effective, or fallback-success facts.

`runtime_records.py` keeps CLI, App-bundled CLI, native-spawn, and App-task
records independent. Probe records are diagnostic-only. `runtime_audit.py`
stores one schema-v1 `runtime_route_audit` per native or independent App-task
attempt. The audit distinguishes `requested_*`, `configured_*`,
`observed_effective_*`, requested/observed sandbox and permission values, and
the failure/status fields. Missing facts remain `unknown`; no artifact may
infer effective native values from an install manifest, probe, TOML, catalog, or
App-task record.

## Acceptance levels

| Level | Commands/evidence | Boundary |
| --- | --- | --- |
| Offline contract/state | `python3 tests/test_runtime_records.py`, `test_routing_state.py`, `test_forward_routing.py`, `test_manifest_audit.py`, `test_skill_contract.py`, `test_agent_contract.py` | Validates closed schemas, route state, helper behavior, and contracts without authentication or network access |
| Offline installer/config | `python3 tests/test_merge_config.py`, `bash tests/test_install.sh`, plus the documentation consistency test | Covers 13-agent installation, dual researcher migration, profiles, backups, idempotency, preserved config, and stale documentation facts |
| Offline bundle validation | `./validate.sh` | Checks shell/Python syntax, payload/Skill/TOML structure, and diagnostic probe structure |
| Offline packaging | `./package.sh` | Runs validation and `tests/run.sh`, then builds and smoke-tests the tarball and self-extracting installer in `dist/` |
| Optional live boundary | `RUN_CODEX_LIVE=1 CODEX_LIVE_EVIDENCE_FILE=... bash tests/test_live_codex.sh` | Schema review only; no authentication or fresh Codex task, and enabled runs always return `UNVERIFIED` |

`tests/run.sh` and `package.sh` deliberately exclude `test_live_codex.sh`.
The optional harness validates supplied evidence without echoing sensitive
values, but it cannot establish live runtime fallback or conformance. A
schema-valid sample is therefore still `UNVERIFIED`.

## Release and packaging behavior

`package.sh` accepts `--output DIR` and `--skip-tests`, runs `validate.sh` and
the offline test gate by default, stages `payload/`, `scripts/`, `tests/`,
`install.sh`, `validate.sh`, `package.sh`, `README.md`,
`DEVELOPMENT_PLAN.md`, and `VERSION`, then produces:

```text
codex-versatile-agent-workflow-<version>.tar.gz
codex-versatile-agent-workflow-offline-installer-<version>.sh
SHA256SUMS
```

It smoke-tests project and user installs with `--check` and does not run the
optional live harness.
