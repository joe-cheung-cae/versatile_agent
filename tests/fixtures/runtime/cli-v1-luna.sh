#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  --version)
    printf 'codex-cli fixture-v1\n'
    ;;
  features)
    printf 'multi_agent stable true\n'
    printf 'multi_agent_v2 stable false\n'
    ;;
  debug)
    printf '%s\n' '{"models":[{"slug":"gpt-5.6-luna","supported_reasoning_levels":[{"effort":"max"}]},{"slug":"gpt-5.6-terra","supported_reasoning_levels":[{"effort":"high"}]}]}'
    ;;
  *)
    exit 2
    ;;
esac
