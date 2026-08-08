#!/usr/bin/env bash
set -euo pipefail

bundle_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
payload_root="$bundle_root/payload"
skill_source="$payload_root/skills/versatile-dev"
common_agents_source="$payload_root/agents/common"
detector="$skill_source/scripts/detect-runtime.sh"
merge_config="$bundle_root/scripts/merge_config.py"
ensure_snippet="$bundle_root/scripts/ensure_snippet.py"
write_manifest="$bundle_root/scripts/write_manifest.py"
version="$(tr -d '[:space:]' < "$bundle_root/VERSION")"

scope="project"
target_path=""
profile="auto"
check_only="false"
dry_run="false"
with_agents_snippet="false"
manage_config="true"
user_home="${HOME:?HOME is required}"
codex_home_override=""
codex_binary="${CODEX_BIN:-}"
app_codex_binary="${APP_CODEX_BIN:-/Applications/ChatGPT.app/Contents/Resources/codex}"
native_v2_luna="${VERSATILE_NATIVE_V2_LUNA:-unknown}"

usage() {
  cat <<'EOF'
Usage: ./install.sh [options]

Scopes:
  --scope project|user|global   Install into a repository or user locations.
  --target PATH                 Project directory for project scope.
  --user-home PATH              Override the user home for isolated installs/tests.
  --codex-home PATH             Override Codex home for user/global scope.

Routing:
  --profile auto|luna-v1|luna-v2|terra-fallback
  --codex-bin PATH
  --app-codex-bin PATH
  --native-v2-luna yes|no|unknown

Behavior:
  --with-agents-snippet         Append an idempotent AGENTS.md activation note.
  --no-config                   Do not merge managed [agents] settings.
  --check                       Verify an existing installation without writing.
  --dry-run                     Print intended changes without writing.
  -h, --help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scope)
      scope="${2:-}"
      shift 2
      ;;
    --target|--repo)
      target_path="${2:-}"
      shift 2
      ;;
    --profile)
      profile="${2:-}"
      shift 2
      ;;
    --user-home)
      user_home="${2:-}"
      shift 2
      ;;
    --codex-home)
      codex_home_override="${2:-}"
      shift 2
      ;;
    --codex-bin)
      codex_binary="${2:-}"
      shift 2
      ;;
    --app-codex-bin)
      app_codex_binary="${2:-}"
      shift 2
      ;;
    --native-v2-luna)
      native_v2_luna="${2:-}"
      shift 2
      ;;
    --with-agents-snippet)
      with_agents_snippet="true"
      shift
      ;;
    --no-config)
      manage_config="false"
      shift
      ;;
    --check)
      check_only="true"
      shift
      ;;
    --dry-run)
      dry_run="true"
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

[[ -d "$skill_source" ]] || { printf 'Missing skill payload: %s\n' "$skill_source" >&2; exit 2; }
[[ -d "$common_agents_source" ]] || { printf 'Missing agent payload: %s\n' "$common_agents_source" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { printf 'python3 is required for safe TOML merge and validation.\n' >&2; exit 2; }
python3 -c 'import tomllib' >/dev/null 2>&1 || { printf 'Python 3.11 or newer is required (tomllib is unavailable).\n' >&2; exit 2; }

shopt -s nullglob
common_agent_files=("$common_agents_source"/*.toml)
shopt -u nullglob
common_agent_count="${#common_agent_files[@]}"
[[ "$common_agent_count" -eq 13 ]] || {
  printf 'Expected 13 common agents, found %s in %s\n' "$common_agent_count" "$common_agents_source" >&2
  exit 2
}

case "$scope" in
  global) scope="user" ;;
  project|user) ;;
  *) printf 'Unsupported scope: %s\n' "$scope" >&2; exit 2 ;;
esac

case "$profile" in
  auto|luna-v1|luna-v2|terra-fallback) ;;
  *) printf 'Unsupported profile: %s\n' "$profile" >&2; exit 2 ;;
esac

case "$native_v2_luna" in
  yes|no|unknown) ;;
  *) printf 'Unsupported --native-v2-luna value: %s\n' "$native_v2_luna" >&2; exit 2 ;;
esac

probe_dir="$(mktemp -d "${TMPDIR:-/tmp}/versatile-agent-probe.XXXXXX")"
trap 'rm -rf "$probe_dir"' EXIT
probe_file="$probe_dir/runtime.json"

detector_args=(--format json --app-codex-bin "$app_codex_binary" --native-v2-luna "$native_v2_luna")
profile_args=(--format profile --app-codex-bin "$app_codex_binary" --native-v2-luna "$native_v2_luna")
if [[ -n "$codex_binary" ]]; then
  detector_args+=(--codex-bin "$codex_binary")
  profile_args+=(--codex-bin "$codex_binary")
fi

"$detector" "${detector_args[@]}" > "$probe_file"
if [[ "$profile" == "auto" ]]; then
  profile="$($detector "${profile_args[@]}")"
fi

if [[ "$scope" == "project" ]]; then
  [[ -n "$target_path" ]] || target_path="$PWD"
  [[ -d "$target_path" ]] || { printf 'Project target does not exist: %s\n' "$target_path" >&2; exit 2; }
  target_path="$(cd "$target_path" && pwd -P)"
  skill_destination="$target_path/.agents/skills/versatile-dev"
  agent_destination="$target_path/.codex/agents"
  config_destination="$target_path/.codex/config.toml"
  manifest_destination="$target_path/.codex/versatile-agent/install-manifest.json"
  agents_md_destination="$target_path/AGENTS.md"
  backup_base="$target_path"
else
  user_home="$(cd "$user_home" && pwd -P)"
  codex_home="${codex_home_override:-${CODEX_HOME:-$user_home/.codex}}"
  skill_destination="$user_home/.agents/skills/versatile-dev"
  agent_destination="$codex_home/agents"
  config_destination="$codex_home/config.toml"
  manifest_destination="$codex_home/versatile-agent/install-manifest.json"
  agents_md_destination="$codex_home/AGENTS.md"
  backup_base="$codex_home"
fi

legacy_destination="$agent_destination/docs_researcher.toml"
historical_luna_sha256="a57cba3c55a1a6abb4340b554a732923743f47b651f82984b8b3f246d824e730"
historical_terra_sha256="a69031a325e3ecf920ab1df09d7cf074c4fe97d301e20c9b27ffb04216bb983b"

classify_legacy_destination() {
  python3 - "$legacy_destination" "$historical_luna_sha256" "$historical_terra_sha256" <<'PY'
import hashlib
import os
import stat
import sys

path, *historical_hashes = sys.argv[1:]
try:
    metadata = os.lstat(path)
except FileNotFoundError:
    print("ABSENT")
    raise SystemExit(0)
except OSError:
    print("CONFLICT")
    raise SystemExit(0)

if not stat.S_ISREG(metadata.st_mode):
    print("CONFLICT")
    raise SystemExit(0)

fd = -1
try:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    opened = os.fstat(fd)
    if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
        print("CONFLICT")
        raise SystemExit(0)
    digest = hashlib.sha256()
    with os.fdopen(fd, "rb", closefd=True) as stream:
        fd = -1
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
except OSError:
    print("CONFLICT")
    raise SystemExit(0)
finally:
    if fd >= 0:
        os.close(fd)

print("KNOWN_HISTORICAL" if digest.hexdigest() in historical_hashes else "CONFLICT")
PY
}

case "$skill_destination" in
  */.agents/skills/versatile-dev|*/skills/versatile-dev) ;;
  *) printf 'Refusing unsafe skill destination: %s\n' "$skill_destination" >&2; exit 2 ;;
esac
case "$agent_destination" in
  /agents|agents|/)
    printf 'Refusing unsafe agent destination: %s\n' "$agent_destination" >&2
    exit 2
    ;;
  */agents|*/agents/) ;;
  *) printf 'Refusing unsafe agent destination: %s\n' "$agent_destination" >&2; exit 2 ;;
esac

legacy_state="$(classify_legacy_destination)"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_destination="$backup_base/.codex-versatile-backup-$timestamp-$$"
backup_created="false"

legacy_conflict() {
  printf 'Legacy agent path conflict: %s\n' "$legacy_destination" >&2
  printf 'The path is not an absent file or a recognized historical payload. Preserve it unchanged, resolve the conflict manually, and rerun installation.\n' >&2
}

if [[ "$legacy_state" == "CONFLICT" ]]; then
  legacy_conflict
  exit 1
fi

if [[ "$check_only" == "true" && "$legacy_state" == "KNOWN_HISTORICAL" ]]; then
  printf 'Legacy migration pending: %s is a recognized historical file; run a normal install to back it up and remove it.\n' "$legacy_destination" >&2
  exit 1
fi

if [[ "$check_only" == "true" ]]; then
  status=0
  if ! diff -qr "$skill_source" "$skill_destination" >/dev/null 2>&1; then
    printf 'Skill installation is missing or stale: %s\n' "$skill_destination" >&2
    status=1
  fi
  for source_file in "${common_agent_files[@]}"; do
    destination_file="$agent_destination/$(basename "$source_file")"
    if ! cmp -s "$source_file" "$destination_file"; then
      printf 'Agent installation is missing or stale: %s\n' "$destination_file" >&2
      status=1
    fi
  done
  if [[ "$manage_config" == "true" ]] && ! python3 "$merge_config" --check "$config_destination"; then
    status=1
  fi
  if [[ "$with_agents_snippet" == "true" ]] && ! python3 "$ensure_snippet" --check "$agents_md_destination" "$payload_root/AGENTS.md.snippet"; then
    printf 'AGENTS.md activation snippet is missing: %s\n' "$agents_md_destination" >&2
    status=1
  fi
  if ! python3 -c '
import json, sys
path, profile, version = sys.argv[1:]
try:
    data = json.load(open(path, encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(1)
raise SystemExit(0 if data.get("selected_profile") == profile and data.get("bundle_version") == version else 1)
' "$manifest_destination" "$profile" "$version"; then
    printf 'Install manifest is missing or does not match profile %s: %s\n' "$profile" "$manifest_destination" >&2
    status=1
  fi
  if [[ "$status" -eq 0 ]]; then
    printf 'Installation check passed: scope=%s profile=%s\n' "$scope" "$profile"
  fi
  exit "$status"
fi

if [[ "$dry_run" == "true" ]]; then
  if [[ "$legacy_state" == "KNOWN_HISTORICAL" ]]; then
    printf 'Would back up legacy file: %s -> %s\n' "$legacy_destination" "$backup_destination/agents/docs_researcher.toml"
    printf 'Would remove legacy file: %s\n' "$legacy_destination"
  fi
  printf 'Would install skill: %s\n' "$skill_destination"
  printf 'Would install %s agents: %s\n' "$common_agent_count" "$agent_destination"
  [[ "$manage_config" == "true" ]] && printf 'Would merge [agents] settings: %s\n' "$config_destination"
  [[ "$with_agents_snippet" == "true" ]] && printf 'Would ensure AGENTS.md snippet: %s\n' "$agents_md_destination"
  printf 'Selected profile: %s\n' "$profile"
  exit 0
fi

ensure_backup_root() {
  if [[ "$backup_created" == "false" ]]; then
    mkdir -p "$backup_destination"
    backup_created="true"
  fi
}

backup_path() {
  local source_path="$1"
  local relative_name="$2"
  if [[ -e "$source_path" || -L "$source_path" ]]; then
    ensure_backup_root
    mkdir -p "$backup_destination/$(dirname "$relative_name")"
    cp -Rp "$source_path" "$backup_destination/$relative_name"
  fi
}

revalidate_migration_pair() {
  python3 - "$legacy_destination" "$legacy_backup_path" "$historical_luna_sha256" "$historical_terra_sha256" <<'PY'
import hashlib
import os
import stat
import sys

destination, backup, *historical_hashes = sys.argv[1:]
historical_hashes = set(historical_hashes)


def open_regular(path: str):
    fd = -1
    try:
        metadata = os.lstat(path)
        if not stat.S_ISREG(metadata.st_mode):
            return None
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino):
            os.close(fd)
            fd = -1
            return None
        stream = os.fdopen(fd, "rb", closefd=True)
        fd = -1
        return stream
    except OSError:
        if fd >= 0:
            os.close(fd)
        return None


destination_stream = open_regular(destination)
backup_stream = open_regular(backup)
valid = destination_stream is not None and backup_stream is not None
destination_digest = hashlib.sha256()
backup_digest = hashlib.sha256()

try:
    if valid:
        while True:
            destination_chunk = destination_stream.read(1024 * 1024)
            backup_chunk = backup_stream.read(1024 * 1024)
            if destination_chunk != backup_chunk:
                valid = False
            destination_digest.update(destination_chunk)
            backup_digest.update(backup_chunk)
            if not destination_chunk and not backup_chunk:
                break
finally:
    if destination_stream is not None:
        destination_stream.close()
    if backup_stream is not None:
        backup_stream.close()

valid = (
    valid
    and destination_digest.hexdigest() in historical_hashes
    and backup_digest.hexdigest() in historical_hashes
    and destination_digest.digest() == backup_digest.digest()
)
print("VALID" if valid else "INVALID")
PY
}

if [[ "$legacy_state" == "KNOWN_HISTORICAL" ]]; then
  legacy_backup_path="$backup_destination/agents/docs_researcher.toml"
  backup_path "$legacy_destination" "agents/docs_researcher.toml"
  if [[ ! -f "$legacy_backup_path" || -L "$legacy_backup_path" ]]; then
    printf 'Legacy migration backup verification failed; preserving %s.\n' "$legacy_destination" >&2
    exit 1
  fi
  if [[ "$(revalidate_migration_pair)" != "VALID" ]]; then
    printf 'Legacy migration revalidation failed; preserving current destination: %s.\n' "$legacy_destination" >&2
    exit 1
  fi
  rm -f "$legacy_destination"
  if [[ -e "$legacy_destination" || -L "$legacy_destination" ]]; then
    printf 'Legacy migration removal failed; preserving %s.\n' "$legacy_destination" >&2
    exit 1
  fi
fi

if [[ ! -d "$skill_destination" ]] || ! diff -qr "$skill_source" "$skill_destination" >/dev/null 2>&1; then
  backup_path "$skill_destination" "skill/versatile-dev"
  mkdir -p "$(dirname "$skill_destination")"
  rm -rf "$skill_destination"
  cp -Rp "$skill_source" "$skill_destination"
fi

mkdir -p "$agent_destination"
for source_file in "${common_agent_files[@]}"; do
  filename="$(basename "$source_file")"
  destination_file="$agent_destination/$filename"
  if ! cmp -s "$source_file" "$destination_file"; then
    backup_path "$destination_file" "agents/$filename"
    install -m 0644 "$source_file" "$destination_file"
  fi
done

if [[ "$manage_config" == "true" ]]; then
  if ! python3 "$merge_config" --check "$config_destination" >/dev/null 2>&1; then
    backup_path "$config_destination" "config.toml"
    python3 "$merge_config" "$config_destination"
  fi
fi

if [[ "$with_agents_snippet" == "true" ]]; then
  if ! python3 "$ensure_snippet" --check "$agents_md_destination" "$payload_root/AGENTS.md.snippet"; then
    backup_path "$agents_md_destination" "AGENTS.md"
    python3 "$ensure_snippet" "$agents_md_destination" "$payload_root/AGENTS.md.snippet"
  fi
fi

if ! python3 -c '
import json, sys
manifest_path, probe_path, profile, scope, version = sys.argv[1:]
try:
    manifest = json.load(open(manifest_path, encoding="utf-8"))
    probe = json.load(open(probe_path, encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(1)
matches = (
    manifest.get("selected_profile") == profile
    and manifest.get("scope") == scope
    and manifest.get("bundle_version") == version
    and manifest.get("runtime_probe") == probe
)
raise SystemExit(0 if matches else 1)
' "$manifest_destination" "$probe_file" "$profile" "$scope" "$version"; then
  backup_path "$manifest_destination" "install-manifest.json"
  python3 "$write_manifest" \
    --output "$manifest_destination" \
    --profile "$profile" \
    --scope "$scope" \
    --source-version "$version" \
    --probe "$probe_file"
fi

printf 'Installed Versatile Agent %s\n' "$version"
printf '  scope:   %s\n' "$scope"
printf '  profile: %s\n' "$profile"
printf '  skill:   %s\n' "$skill_destination"
printf '  agents:  %s common custom agents at %s\n' "$common_agent_count" "$agent_destination"
printf '  manifest:%s\n' " $manifest_destination"
if [[ "$backup_created" == "true" ]]; then
  printf '  backup:  %s\n' "$backup_destination"
fi
printf 'Start a fresh Codex task so skill and agent discovery reloads the installed files.\n'
