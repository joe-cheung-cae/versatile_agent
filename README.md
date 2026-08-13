# Codex Versatile Agent Workflow

Offline-capable Codex bundle for an adaptive engineering lead, one reusable
`versatile-dev` Skill, and 13 unique narrow custom agents. The bundle includes
two distinct documentation researchers that can be used as a controlled Luna-
first/Terra-second route. Installation profiles and diagnostic probes do not
prove an effective native route, and this bundle does not make the Codex CLI
automatically switch models.

The implementation and acceptance record is in
[DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md).

## What is included

- An adaptive lead policy instead of a fixed orchestration DAG.
- 13 unique agents: `code_mapper`, `architect`, `implementer`, `tester`,
  `test_validator`, `reviewer`, `gpu_reviewer`, `numerics_reviewer`,
  `parallelism_reviewer`, `performance_profiler`, `security_reviewer`,
  `docs_researcher_luna`, and `docs_researcher_terra`.
- Two simultaneous documentation-researcher profiles with distinct names and
  files: Luna requests `gpt-5.6-luna` / `max`; Terra requests
  `gpt-5.6-terra` / `high`. Both are read-only.
- Safe `[agents]` config merge that preserves unrelated TOML.
- Idempotent project and user/global installation with recoverable backups and
  historical single-researcher migration.
- Deterministic offline routing, runtime-record, and per-attempt audit helpers.
- Offline contract, state-machine, installer, and packaging checks, plus an
  optional schema-review harness whose result remains unverified.

## Install from this source tree

Prerequisites: Bash, Python 3.11 or newer, `tar`, and either `shasum` or
`sha256sum` when building artifacts. Installation itself does not need network
access.

Project scope:

```bash
./install.sh --scope project --target /path/to/repository --profile auto
```

User/global scope:

```bash
./install.sh --scope user --profile auto
```

Current Codex discovery locations are:

- Project Skill: `<repo>/.agents/skills/versatile-dev`
- Project agents: `<repo>/.codex/agents/*.toml`
- User Skill: `$HOME/.agents/skills/versatile-dev`
- User agents: `${CODEX_HOME:-$HOME/.codex}/agents/*.toml`

Use `--with-agents-snippet` to append a small, idempotent activation note to
project `AGENTS.md` or user `${CODEX_HOME:-$HOME/.codex}/AGENTS.md`.

The installer writes a schema-v2 `install-manifest.json` beside the Codex
configuration. It records installation/configuration facts, including the
install-time `selected_profile`, 13 installed agent identities, and the two
configured researcher pins. It does not record probe, observed, effective,
capability, or fallback-success facts. `selected_profile` is a legacy
compatibility selector, not an effective runtime route. Start a fresh Codex
task after installation so discovery reloads the Skill and custom agents.

The bundle always installs the two distinct researcher files
`docs_researcher_luna.toml` and `docs_researcher_terra.toml`; it never uses two
profiles that overwrite the same `docs_researcher.toml` destination. A
recognized historical `docs_researcher.toml` is backed up and removed during a
normal install. `--check` reports migration pending until that is done, while
customized, symlink, and directory conflicts are preserved and fail closed.
`--dry-run` reports the migration without writing it.

## Compatibility profiles and native routing

The accepted installer selectors are:

- `auto`: probes the selected CLI and App-bundled CLI and converts the
  diagnostic result into a compatibility profile.
- `luna-v1`, `luna-v2`, and `terra-fallback`: retained legacy profile names for
  compatibility with existing install commands and manifests.

The probe, model catalog, `--native-v2-luna`, TOML pins, and compatibility
profile are diagnostic or configured facts only. They cannot establish that a
native spawn accepted a model, effort, agent type, or route. Unknown,
conflicting, or unobservable facts remain unknown and fail closed.

For a classified documentation task, the Skill-owned route is explicit:

1. Run the same-interface PRECHECK, which must expose both researcher names.
2. Request `docs_researcher_luna` first.
3. Permit exactly one `docs_researcher_terra` attempt only after a classified
   native routing rejection or complete same-attempt native mismatch, with the
   same canonical `task_packet_hash`.
4. Treat content, tool, and task failures as terminal `STOP_FAILED`; a timeout
   is `STOP_FAILED` only when route metadata is complete and non-conflicting.
   Missing, conflicting, unobservable, or unknown route evidence is
   `STOP_UNVERIFIED`. These outcomes do not authorize Terra.

`payload/skills/versatile-dev/scripts/forward_router.py` accepts a closed,
already-classified packet and can produce an offline plan or replay a complete
route document:

```text
python3 payload/skills/versatile-dev/scripts/forward_router.py plan -
python3 payload/skills/versatile-dev/scripts/forward_router.py replay PACKET.json ROUTE.json
```

The helper validates canonical packet hashes and route state; it does not
classify English, spawn agents, probe, authenticate, access the network, or
invent native effective metadata. The parent Skill remains the authority for
native spawn and App actions.

The Codex App's user-visible task lane is separate from native subagents and
from Luna-to-Terra routing. It requires explicit authorization in the current
user request. App requested/observed facts cannot populate native effective
facts. The App lane used for this P3 development session is configured as
`gpt-5.6-luna` / `max`; that is App-task context only, not repository or native
runtime evidence.

## Evidence and audit boundaries

The installation manifest and each runtime attempt are separate artifacts:

| Fact layer | What may establish it | What it cannot establish |
| --- | --- | --- |
| installed | Installed paths and manifest identities | The route used by a task |
| configured | TOML pins and `[agents]` defaults | That native runtime accepted them |
| capability | CLI/App-bundled CLI probe and model catalog | That a native attempt accepted or used them |
| requested | This attempt's requested agent/model/effort | That the request was accepted |
| observed | Same-attempt native details and sandbox/permission details | Values that were not returned |
| effective | A complete tuple from same-attempt native details | Inferences from probe, catalog, TOML, or App facts |

`runtime_records.py` keeps CLI, App-bundled CLI, native-spawn, and App-task
records independent. `runtime_audit.py` writes a separate schema-v1,
per-attempt `runtime_route_audit`; it preserves `unknown` instead of filling
missing requested, configured, observed, or effective values. The manifest,
probe, and App task cannot fill native effective fields.

## Validate and package

The offline gates are:

```bash
./validate.sh
./tests/run.sh
./package.sh
```

`validate.sh` checks shell/Python syntax, payload contracts, TOML, Skill
structure, and runtime-probe structure. `tests/run.sh` runs the offline runtime,
routing, manifest/audit, Skill/agent contract, config-merge, documentation, and
installer tests; it does not run the optional live harness. `package.sh` runs
validation and the offline test gate, copies the payload/scripts/tests and root
documentation into a staging bundle, builds the tarball and self-extracting
installer under `dist/`, smoke-tests project and user installs, and writes
`SHA256SUMS`.

The optional live boundary is explicit:

```bash
RUN_CODEX_LIVE=1 \
CODEX_LIVE_EVIDENCE_FILE=/path/to/evidence.json \
bash tests/test_live_codex.sh
```

`tests/test_live_codex.sh` is a schema-review harness only. It does not
authenticate, run a fresh Codex task, or establish live fallback/conformance;
when enabled it always returns `UNVERIFIED`, including for schema-valid sample
evidence. The offline gates likewise do not claim live runtime conformance.

## Offline installer

After copying the generated single file to another machine:

```bash
chmod +x codex-versatile-agent-workflow-offline-installer-<version>.sh
./codex-versatile-agent-workflow-offline-installer-<version>.sh \
  --scope project \
  --target /path/to/repository \
  --profile auto
```

The bundle installs offline. Actual model execution still depends on the target
machine's Codex authentication, provider, model availability, and runtime
policy.

## Verification-only commands

```bash
./install.sh --scope project --target /path/to/repository --profile auto --check
./install.sh --scope project --target /path/to/repository --profile auto --dry-run
```

Official references used for the design:

- [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents.md)
- [Codex skills](https://learn.chatgpt.com/docs/skills)
- [Codex configuration](https://learn.chatgpt.com/docs/config-file/config-reference)

## License

This project is licensed under the [MIT License](LICENSE).
