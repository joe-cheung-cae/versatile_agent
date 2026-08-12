#!/usr/bin/env bash
set -euo pipefail

bundle_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

python3 "$bundle_root/tests/test_runtime_records.py"
python3 "$bundle_root/tests/test_routing_state.py"
python3 "$bundle_root/tests/test_forward_routing.py"
python3 "$bundle_root/tests/test_manifest_audit.py"
python3 "$bundle_root/tests/test_skill_contract.py"
python3 "$bundle_root/tests/test_agent_contract.py"
python3 "$bundle_root/tests/test_merge_config.py"
"$bundle_root/tests/test_install.sh"

printf 'All bundle tests passed.\n'
