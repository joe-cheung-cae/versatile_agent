#!/usr/bin/env bash
set -euo pipefail

bundle_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

python3 "$bundle_root/tests/test_merge_config.py"
"$bundle_root/tests/test_install.sh"

printf 'All bundle tests passed.\n'
