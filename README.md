# Codex Versatile Agent Workflow

Offline-capable Codex bundle for an adaptive engineering lead, one reusable
`versatile-dev` Skill, and twelve narrow custom agents. It supports project and
user/global installation, runtime capability detection, Luna/Max routing for
compatible V1 or verified V2 interfaces, and an explicit Terra fallback.

The implementation phases, acceptance matrix, runtime snapshot, and risk
controls are recorded in [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md).

## What is included

- Adaptive lead policy instead of a fixed orchestration DAG.
- Twelve agents: mapping, documentation, architecture, implementation, testing,
  test validation, general review, GPU review, numerical review, parallelism
  review, profiling, and security review.
- Sol for high-consequence planning/review, Terra for implementation and the
  fallback lane, and Luna/Max for the narrow documentation lane when supported.
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
records the selected route, and backs up changed files before replacement.
Start a fresh Codex task after installation so discovery reloads the Skill and
custom agents.

## Routing profiles

- `auto`: probe the selected CLI and App-bundled CLI.
- `luna-v1`: pin `docs_researcher` to `gpt-5.6-luna` with `max` effort.
- `luna-v2`: use the same Luna/Max definition only after the active V2 spawn
  interface explicitly exposes Luna.
- `terra-fallback`: pin `docs_researcher` to `gpt-5.6-terra` with `high` effort.

When V2 is present but the live spawn interface does not expose Luna, `auto`
selects `terra-fallback`. To pass verified live-interface evidence into the
offline probe, use `--native-v2-luna yes`. The Skill also requires the lead to
record requested and effective routing instead of silently substituting models.

The App's separate user-visible task interface may support Luna/Max even when
native spawning does not. The Skill treats that as a distinct, explicit-opt-in
route; it never creates a visible task merely as a hidden fallback.

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
