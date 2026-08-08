#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  --version)
    printf 'ChatGPT App fixture-v1\n'
    ;;
  features)
    printf 'multi_agent stable true\n'
    printf 'multi_agent_v2 stable false\n'
    ;;
  debug)
    printf '%s\n' '{"models":[{"slug":"gpt-5.6-luna","supported_reasoning_levels":[{"effort":"max"}]}]}'
    ;;
  *)
    exit 2
    ;;
esac
