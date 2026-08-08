#!/usr/bin/env bash
set -euo pipefail

bundle_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
test_root="$(mktemp -d "${TMPDIR:-/tmp}/versatile-agent-tests.XXXXXX")"
trap 'rm -rf "$test_root"' EXIT

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

assert_file() {
  [[ -f "$1" ]] || fail "expected file $1"
}

assert_dir() {
  [[ -d "$1" ]] || fail "expected directory $1"
}

assert_absent() {
  [[ ! -e "$1" ]] || fail "expected no path at $1"
}

assert_contains() {
  grep -Fq "$2" "$1" || fail "expected $1 to contain $2"
}

project_luna="$test_root/project-luna"
mkdir -p "$project_luna/.codex"
cat > "$project_luna/.codex/config.toml" <<'EOF'
model = "keep-me"

[agents]
max_concurrent_threads_per_session = 2
custom_key = "preserve"

[features]
example = true
EOF

"$bundle_root/install.sh" \
  --scope project \
  --target "$project_luna" \
  --profile luna-v1 \
  --with-agents-snippet

assert_dir "$project_luna/.agents/skills/versatile-dev"
assert_file "$project_luna/.codex/agents/docs_researcher.toml"
assert_file "$project_luna/.codex/versatile-agent/install-manifest.json"
assert_contains "$project_luna/.codex/agents/docs_researcher.toml" 'model = "gpt-5.6-luna"'
assert_contains "$project_luna/.codex/agents/docs_researcher.toml" 'model_reasoning_effort = "max"'
assert_contains "$project_luna/.codex/config.toml" 'model = "keep-me"'
assert_contains "$project_luna/.codex/config.toml" 'custom_key = "preserve"'
assert_contains "$project_luna/.codex/config.toml" 'example = true'
assert_contains "$project_luna/.codex/config.toml" 'max_concurrent_threads_per_session = 6'
assert_contains "$project_luna/AGENTS.md" '## Versatile development workflow'

agent_count="$(find "$project_luna/.codex/agents" -maxdepth 1 -type f -name '*.toml' | wc -l | tr -d '[:space:]')"
[[ "$agent_count" == "12" ]] || fail "expected 12 project agents, found $agent_count"
find "$project_luna" -maxdepth 1 -type d -name '.codex-versatile-backup-*' | grep -q . || fail "expected config backup"

"$bundle_root/install.sh" \
  --scope project \
  --target "$project_luna" \
  --profile luna-v1 \
  --with-agents-snippet \
  --check

backup_count_before="$(find "$project_luna" -maxdepth 1 -type d -name '.codex-versatile-backup-*' | wc -l | tr -d '[:space:]')"
"$bundle_root/install.sh" \
  --scope project \
  --target "$project_luna" \
  --profile luna-v1 \
  --with-agents-snippet >/dev/null
backup_count_after="$(find "$project_luna" -maxdepth 1 -type d -name '.codex-versatile-backup-*' | wc -l | tr -d '[:space:]')"
[[ "$backup_count_before" == "$backup_count_after" ]] || fail "idempotent reinstall created an unnecessary backup"

marker_count="$(grep -Fc '## Versatile development workflow' "$project_luna/AGENTS.md")"
[[ "$marker_count" == "1" ]] || fail "AGENTS.md snippet must be idempotent"

project_fallback="$test_root/project-fallback"
mkdir -p "$project_fallback"
"$bundle_root/install.sh" --scope project --target "$project_fallback" --profile terra-fallback >/dev/null
assert_contains "$project_fallback/.codex/agents/docs_researcher.toml" 'model = "gpt-5.6-terra"'
assert_contains "$project_fallback/.codex/agents/docs_researcher.toml" 'model_reasoning_effort = "high"'

fake_home="$test_root/user-home"
fake_codex_home="$test_root/user-codex"
mkdir -p "$fake_home" "$fake_codex_home"
"$bundle_root/install.sh" \
  --scope user \
  --user-home "$fake_home" \
  --codex-home "$fake_codex_home" \
  --profile terra-fallback >/dev/null
assert_file "$fake_home/.agents/skills/versatile-dev/SKILL.md"
assert_file "$fake_codex_home/agents/reviewer.toml"
assert_file "$fake_codex_home/config.toml"
assert_file "$fake_codex_home/versatile-agent/install-manifest.json"

project_dry="$test_root/project-dry"
mkdir -p "$project_dry"
"$bundle_root/install.sh" --scope project --target "$project_dry" --profile terra-fallback --dry-run >/dev/null
assert_absent "$project_dry/.codex"
assert_absent "$project_dry/.agents"

fake_v1="$test_root/fake-codex-v1"
cat > "$fake_v1" <<'EOF'
#!/usr/bin/env bash
set -e
case "${1:-}" in
  --version)
    printf 'codex-cli test-v1\n'
    ;;
  features)
    printf 'multi_agent stable true\n'
    printf 'multi_agent_v2 stable false\n'
    ;;
  debug)
    printf '%s\n' '{"models":[{"slug":"gpt-5.6-luna","supported_reasoning_levels":[{"effort":"max"}]}]}'
    ;;
  *) exit 2 ;;
esac
EOF
chmod +x "$fake_v1"

project_auto_v1="$test_root/project-auto-v1"
mkdir -p "$project_auto_v1"
"$bundle_root/install.sh" \
  --scope project \
  --target "$project_auto_v1" \
  --profile auto \
  --codex-bin "$fake_v1" \
  --app-codex-bin "$test_root/missing-app-codex" >/dev/null
assert_contains "$project_auto_v1/.codex/agents/docs_researcher.toml" 'model = "gpt-5.6-luna"'
assert_contains "$project_auto_v1/.codex/versatile-agent/install-manifest.json" '"selected_profile": "luna-v1"'

fake_v2="$test_root/fake-codex-v2"
cat > "$fake_v2" <<'EOF'
#!/usr/bin/env bash
set -e
case "${1:-}" in
  --version)
    printf 'codex-cli test-v2\n'
    ;;
  features)
    printf 'multi_agent stable true\n'
    printf 'multi_agent_v2 stable true\n'
    ;;
  debug)
    printf '%s\n' '{"models":[{"slug":"gpt-5.6-luna","supported_reasoning_levels":[{"effort":"max"}]}]}'
    ;;
  *) exit 2 ;;
esac
EOF
chmod +x "$fake_v2"

project_auto_v2="$test_root/project-auto-v2"
mkdir -p "$project_auto_v2"
"$bundle_root/install.sh" \
  --scope project \
  --target "$project_auto_v2" \
  --profile auto \
  --codex-bin "$fake_v2" \
  --app-codex-bin "$test_root/missing-app-codex" >/dev/null
assert_contains "$project_auto_v2/.codex/agents/docs_researcher.toml" 'model = "gpt-5.6-terra"'
assert_contains "$project_auto_v2/.codex/versatile-agent/install-manifest.json" '"selected_profile": "terra-fallback"'

project_auto_v2_luna="$test_root/project-auto-v2-luna"
mkdir -p "$project_auto_v2_luna"
"$bundle_root/install.sh" \
  --scope project \
  --target "$project_auto_v2_luna" \
  --profile auto \
  --codex-bin "$fake_v2" \
  --app-codex-bin "$test_root/missing-app-codex" \
  --native-v2-luna yes >/dev/null
assert_contains "$project_auto_v2_luna/.codex/agents/docs_researcher.toml" 'model = "gpt-5.6-luna"'
assert_contains "$project_auto_v2_luna/.codex/versatile-agent/install-manifest.json" '"selected_profile": "luna-v2"'

printf 'Installer matrix passed: project, user, Luna V1, V2 fallback, V2 Luna, merge, backup, dry-run, and idempotency.\n'
