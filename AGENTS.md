# Repository Guidelines

## Project Structure & Module Organization

This repository builds an offline Codex workflow bundle. `payload/` is source-only: the `versatile-dev` Skill lives in `payload/skills/versatile-dev/`, and the 13 files in `payload/agents/common/` are the only install sources. Codex 0.147 discovers skills from `<repo>/.agents/skills` and `$HOME/.agents/skills`, and agents from `.codex/agents`, only after `install.sh`. Root scripts (`install.sh`, `validate.sh`, and `package.sh`) drive installation and release workflows. Python helpers belong in `scripts/`; automated checks belong in `tests/`. Treat `dist/` as generated release output, not source.

## Build, Test, and Development Commands

- `./validate.sh` performs syntax/structure/diagnostic-probe validation only; it is not live Codex runtime detection.
- `./tests/run.sh` runs the Python unit tests and the Bash installer matrix.
- `python3 tests/test_merge_config.py` runs the focused config-merge suite.
- `./install.sh --scope project --target . --profile terra-fallback --dry-run` previews an install without writing files.
- `./package.sh` runs validation and tests, then creates and smoke-tests the archive, offline installer, and checksums in `dist/`.

Installation requires Bash and Python 3.11+. Packaging also requires `tar` and either `shasum` or `sha256sum`. The workflow is designed to run without network access.

## Coding Style & Naming Conventions

Use four spaces in Python, type hints for public helpers, `pathlib.Path`, `snake_case` functions and variables, and `CapWords` test classes. Bash scripts must start with `#!/usr/bin/env bash` and `set -euo pipefail`; indent blocks by two spaces, quote expansions, and use `snake_case` variables. Name tests `test_*.py` or `test_*.sh`; use lowercase underscores for agent files and kebab-case for profile directories. No formatter or linter is configured, so follow nearby code and use `./validate.sh` as the syntax and structural gate.

## Testing Guidelines

Add focused unit tests for Python behavior and extend `tests/test_install.sh` for end-to-end installation changes. Tests should use temporary directories, clean up with traps, remain offline, and verify closed schemas, installer behavior, and replay helpers — not live native routing. There is no numeric coverage threshold; every behavior change should include a regression assertion. Run `./tests/run.sh` before submitting.

## Commit & Pull Request Guidelines

Start with short, imperative subjects such as `Add V2 fallback routing test`, and keep each commit to one logical change. Pull requests should explain the motivation, affected install/profile paths, validation performed, and any compatibility or offline-packaging impact; link relevant issues. Include generated artifacts or checksum changes only for release-focused work. Screenshots are generally unnecessary because the project has no UI.
