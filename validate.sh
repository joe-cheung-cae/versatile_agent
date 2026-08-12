#!/usr/bin/env bash
set -euo pipefail

bundle_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

bash -n "$bundle_root/install.sh"
bash -n "$bundle_root/validate.sh"
bash -n "$bundle_root/package.sh"
bash -n "$bundle_root/scripts/self-extracting-header.sh"
bash -n "$bundle_root/tests/run.sh"
bash -n "$bundle_root/tests/test_install.sh"
bash -n "$bundle_root/tests/test_live_codex.sh"
bash -n "$bundle_root/payload/skills/versatile-dev/scripts/detect-runtime.sh"

python3 -c '
import pathlib, sys
for name in sys.argv[1:]:
    source = pathlib.Path(name).read_text(encoding="utf-8")
    compile(source, name, "exec")
' \
  "$bundle_root/scripts/merge_config.py" \
  "$bundle_root/scripts/ensure_snippet.py" \
  "$bundle_root/scripts/write_manifest.py" \
  "$bundle_root/scripts/validate_bundle.py" \
  "$bundle_root/payload/skills/versatile-dev/scripts/forward_router.py"

python3 "$bundle_root/scripts/validate_bundle.py" "$bundle_root"
python3 -c 'import json,sys; json.load(sys.stdin)' < <(
  "$bundle_root/payload/skills/versatile-dev/scripts/detect-runtime.sh" --format json
)

printf 'Shell, Python, payload, TOML, skill, and runtime-probe validation passed.\n'
