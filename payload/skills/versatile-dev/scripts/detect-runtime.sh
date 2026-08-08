#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ "$#" -gt 0 && ( "$1" == "-h" || "$1" == "--help" ) ]]; then
  exec python3 "$script_dir/runtime_records.py" detect --help
fi
exec python3 "$script_dir/runtime_records.py" detect "$@"
