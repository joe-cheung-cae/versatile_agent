#!/usr/bin/env bash
set -euo pipefail

bundle_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
version="$(tr -d '[:space:]' < "$bundle_root/VERSION")"
output_dir="$bundle_root/dist"
run_tests="true"

usage() {
  cat <<'EOF'
Usage: ./package.sh [--output DIR] [--skip-tests]

Builds:
  codex-versatile-agent-workflow-<version>.tar.gz
  codex-versatile-agent-workflow-offline-installer-<version>.sh
  SHA256SUMS
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      output_dir="${2:-}"
      shift 2
      ;;
    --skip-tests)
      run_tests="false"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown argument: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

"$bundle_root/validate.sh"
if [[ "$run_tests" == "true" ]]; then
  "$bundle_root/tests/run.sh"
fi

mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd -P)"
bundle_name="codex-versatile-agent-workflow-$version"
archive_path="$output_dir/$bundle_name.tar.gz"
installer_path="$output_dir/codex-versatile-agent-workflow-offline-installer-$version.sh"
checksum_path="$output_dir/SHA256SUMS"

rm -f "$archive_path" "$installer_path" "$checksum_path"

staging_root="$(mktemp -d "${TMPDIR:-/tmp}/versatile-agent-package.XXXXXX")"
trap 'rm -rf "$staging_root"' EXIT
staging_bundle="$staging_root/$bundle_name"
mkdir -p "$staging_bundle"

cp -Rp \
  "$bundle_root/payload" \
  "$bundle_root/scripts" \
  "$bundle_root/tests" \
  "$staging_bundle/"
cp -p \
  "$bundle_root/install.sh" \
  "$bundle_root/validate.sh" \
  "$bundle_root/package.sh" \
  "$bundle_root/README.md" \
  "$bundle_root/DEVELOPMENT_PLAN.md" \
  "$bundle_root/VERSION" \
  "$staging_bundle/"

"$staging_bundle/validate.sh"
tar -czf "$archive_path" -C "$staging_root" "$bundle_name"
cat "$bundle_root/scripts/self-extracting-header.sh" "$archive_path" > "$installer_path"
chmod 0755 "$installer_path"

smoke_project="$staging_root/smoke-project"
mkdir -p "$smoke_project"
"$installer_path" --scope project --target "$smoke_project" --profile terra-fallback >/dev/null
"$installer_path" --scope project --target "$smoke_project" --profile terra-fallback --check >/dev/null

smoke_user_home="$staging_root/smoke-user-home"
smoke_codex_home="$staging_root/smoke-user-codex"
mkdir -p "$smoke_user_home" "$smoke_codex_home"
"$installer_path" \
  --scope user \
  --user-home "$smoke_user_home" \
  --codex-home "$smoke_codex_home" \
  --profile luna-v1 >/dev/null
"$installer_path" \
  --scope user \
  --user-home "$smoke_user_home" \
  --codex-home "$smoke_codex_home" \
  --profile luna-v1 \
  --check >/dev/null

if command -v shasum >/dev/null 2>&1; then
  (
    cd "$output_dir"
    shasum -a 256 "$(basename "$archive_path")" "$(basename "$installer_path")" > "$checksum_path"
  )
elif command -v sha256sum >/dev/null 2>&1; then
  (
    cd "$output_dir"
    sha256sum "$(basename "$archive_path")" "$(basename "$installer_path")" > "$checksum_path"
  )
else
  printf 'Neither shasum nor sha256sum is available.\n' >&2
  exit 2
fi

printf 'Artifacts built and smoke-tested:\n'
printf '  %s\n' "$archive_path"
printf '  %s\n' "$installer_path"
printf '  %s\n' "$checksum_path"
