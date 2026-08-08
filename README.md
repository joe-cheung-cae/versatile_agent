# Codex Versatile Agent Workflow

Offline-capable Codex bundle for an adaptive engineering lead, one reusable
`versatile-dev` Skill, and twelve narrow custom agents. It supports project and
user/global installation plus runtime capability diagnostics. It does **not**
prove an effective native route or make Codex CLI automatically switch models.

The implementation phases, acceptance matrix, runtime snapshot, and risk
controls are recorded in [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md).

## What is included

- Adaptive lead policy instead of a fixed orchestration DAG.
- Twelve agents: mapping, documentation, architecture, implementation, testing,
  test validation, general review, GPU review, numerical review, parallelism
  review, profiling, and security review.
- Role guidance assigns high-consequence planning/review to Sol and implementation
  to Terra. Luna/Max remains capability-dependent; these assignments and
  configuration pins are not runtime proof.
- Safe `[agents]` config merge that preserves unrelated TOML.
- Idempotent project and user/global installation with recoverable backups.
- Validation, installation-matrix tests, tarball packaging, a self-extracting
  Bash installer, and SHA-256 checksums.

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

The installer writes `install-manifest.json` beside the Codex configuration,
records the install-time `selected_profile`, and backs up changed files before
replacement. `selected_profile` is not an effective runtime route. Start a fresh
Codex task after installation so discovery reloads the Skill and custom agents.

## Routing profiles

- `auto`: probes the selected CLI and App-bundled CLI, then selects an
  install-time profile.
- `luna-v1` / `luna-v2`: legacy profiles that configure `docs_researcher` with
  `gpt-5.6-luna` / `max`.
- `terra-fallback`: legacy profile that configures `docs_researcher` with
  `gpt-5.6-terra` / `high`.

The probe and `--native-v2-luna yes` are diagnostic/capability inputs only;
they do not provide verified live-interface or effective-route evidence. The
current installer selects one legacy `docs_researcher` profile, so it cannot
implement the target two-agent route by itself. That legacy agent may receive
one research delegation only when the active interface exposes exactly
`docs_researcher` and same-attempt native details verify its configured
agent/model/effort; it is a single configured route, not fallback success.
Missing or conflicting exposure/effective evidence is `STOP_UNVERIFIED` and
does not authorize an alternate role.

The frozen target contract is explicit Skill orchestration: first
`docs_researcher_luna` (`gpt-5.6-luna` / `max`), then at most one
`docs_researcher_terra` (`gpt-5.6-terra` / `high`) only after a classified Luna
native-routing failure and with the same canonical task packet. Missing or
unknown effective metadata stops as `STOP_UNVERIFIED`; content, tool, task,
timeout, and unknown-exception failures do not trigger Terra. This is not Codex
CLI automatic fallback.

P0 freezes this contract and its audit semantics only. The dual-agent installer,
deterministic route helper, and live conformance verification are future work;
this repository does not yet claim them as implemented or verified.

The App's separate user-visible task interface is a distinct, explicit-opt-in
lane. If its active task tool accepts Luna/Max, that is App-task evidence only;
it does not substitute for native spawning or prove native effective routing.

## Validate and package

```bash
./validate.sh
./tests/run.sh
./package.sh
```

`package.sh` runs validation and tests, builds both deliverables in `dist/`,
executes a clean self-extracting-installer smoke test, and writes `SHA256SUMS`.

## Offline installer

After copying the generated single file to another machine:

```bash
chmod +x codex-versatile-agent-workflow-offline-installer-0.1.0.sh
./codex-versatile-agent-workflow-offline-installer-0.1.0.sh \
  --scope project \
  --target /path/to/repository \
  --profile auto
```

The bundle installs offline. Actual model execution still depends on the target
machine's Codex authentication, provider, model availability, and runtime policy.

## Verification-only commands

```bash
./install.sh --scope project --target /path/to/repository --profile auto --check
./install.sh --scope project --target /path/to/repository --profile auto --dry-run
```

Official references used for the design:

- [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents.md)
- [Codex skills](https://learn.chatgpt.com/docs/skills)
- [Codex configuration](https://learn.chatgpt.com/docs/config-file/config-reference)
