#!/usr/bin/env bash
set -euo pipefail

output_format="json"
codex_candidate="${CODEX_BIN:-}"
app_codex_candidate="${APP_CODEX_BIN:-/Applications/ChatGPT.app/Contents/Resources/codex}"
native_v2_luna="${VERSATILE_NATIVE_V2_LUNA:-unknown}"

usage() {
  printf '%s\n' "Usage: detect-runtime.sh [--format json|env|profile] [--codex-bin PATH] [--app-codex-bin PATH] [--native-v2-luna yes|no|unknown]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --format)
      output_format="${2:-}"
      shift 2
      ;;
    --codex-bin)
      codex_candidate="${2:-}"
      shift 2
      ;;
    --app-codex-bin)
      app_codex_candidate="${2:-}"
      shift 2
      ;;
    --native-v2-luna)
      native_v2_luna="${2:-}"
      shift 2
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

case "$output_format" in
  json|env|profile) ;;
  *)
    printf 'Unsupported format: %s\n' "$output_format" >&2
    exit 2
    ;;
esac

case "$native_v2_luna" in
  yes|no|unknown) ;;
  *)
    printf 'Unsupported --native-v2-luna value: %s\n' "$native_v2_luna" >&2
    exit 2
    ;;
esac

if [[ -z "$codex_candidate" ]]; then
  codex_candidate="$(command -v codex 2>/dev/null || true)"
fi

feature_value() {
  local feature_text="$1"
  local feature_name="$2"
  awk -v wanted="$feature_name" '$1 == wanted { print $3; exit }' <<<"$feature_text"
}

probe_binary() {
  local binary_path="$1"
  local prefix="$2"
  local version="unavailable"
  local features=""
  local models=""
  local multi_agent="false"
  local multi_agent_v2="false"
  local luna="false"
  local luna_max="false"

  if [[ -n "$binary_path" && -x "$binary_path" ]]; then
    version="$($binary_path --version 2>/dev/null | tail -n 1 || true)"
    features="$($binary_path features list 2>/dev/null || true)"
    multi_agent="$(feature_value "$features" "multi_agent")"
    multi_agent_v2="$(feature_value "$features" "multi_agent_v2")"
    [[ "$multi_agent" == "true" ]] || multi_agent="false"
    [[ "$multi_agent_v2" == "true" ]] || multi_agent_v2="false"

    models="$($binary_path debug models --bundled 2>/dev/null || true)"
    if [[ -n "$models" ]] && command -v python3 >/dev/null 2>&1; then
      read -r luna luna_max < <(
        python3 -c '
import json
import sys

try:
    data = json.load(sys.stdin)
    model = next((item for item in data.get("models", []) if item.get("slug") == "gpt-5.6-luna"), None)
    efforts = {item.get("effort") for item in (model or {}).get("supported_reasoning_levels", [])}
    print("true" if model else "false", "true" if "max" in efforts else "false")
except Exception:
    print("false false")
' <<<"$models"
      )
    else
      if grep -q '"slug":"gpt-5.6-luna"' <<<"$models"; then
        luna="true"
      fi
    fi
  fi

  printf -v "${prefix}_path" '%s' "$binary_path"
  printf -v "${prefix}_version" '%s' "$version"
  printf -v "${prefix}_multi_agent" '%s' "$multi_agent"
  printf -v "${prefix}_multi_agent_v2" '%s' "$multi_agent_v2"
  printf -v "${prefix}_luna" '%s' "$luna"
  printf -v "${prefix}_luna_max" '%s' "$luna_max"
}

probe_binary "$codex_candidate" "cli"
probe_binary "$app_codex_candidate" "app"

recommended_profile="terra-fallback"
route_reason="No verified Luna route; use the Terra fallback."

if [[ "$cli_multi_agent_v2" == "true" || "$app_multi_agent_v2" == "true" ]]; then
  if [[ "$native_v2_luna" == "yes" && ( "$cli_luna_max" == "true" || "$app_luna_max" == "true" ) ]]; then
    recommended_profile="luna-v2"
    route_reason="Native V2 and Luna/Max were explicitly verified."
  else
    recommended_profile="terra-fallback"
    route_reason="Native V2 is present but Luna/Max was not exposed by the active spawn interface."
  fi
elif [[ "$cli_multi_agent" == "true" && "$cli_luna_max" == "true" ]]; then
  recommended_profile="luna-v1"
  route_reason="CLI V1 custom agents and Luna/Max are available."
elif [[ "$app_multi_agent" == "true" && "$app_luna_max" == "true" ]]; then
  recommended_profile="luna-v1"
  route_reason="App-bundled V1 custom agents and Luna/Max are available."
fi

json_escape() {
  python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'
}

if [[ "$output_format" == "profile" ]]; then
  printf '%s\n' "$recommended_profile"
  exit 0
fi

if [[ "$output_format" == "env" ]]; then
  printf 'CLI_PATH=%q\n' "$cli_path"
  printf 'CLI_VERSION=%q\n' "$cli_version"
  printf 'CLI_MULTI_AGENT=%q\n' "$cli_multi_agent"
  printf 'CLI_MULTI_AGENT_V2=%q\n' "$cli_multi_agent_v2"
  printf 'CLI_LUNA=%q\n' "$cli_luna"
  printf 'CLI_LUNA_MAX=%q\n' "$cli_luna_max"
  printf 'APP_CODEX_PATH=%q\n' "$app_path"
  printf 'APP_CODEX_VERSION=%q\n' "$app_version"
  printf 'APP_MULTI_AGENT=%q\n' "$app_multi_agent"
  printf 'APP_MULTI_AGENT_V2=%q\n' "$app_multi_agent_v2"
  printf 'APP_LUNA=%q\n' "$app_luna"
  printf 'APP_LUNA_MAX=%q\n' "$app_luna_max"
  printf 'NATIVE_V2_LUNA=%q\n' "$native_v2_luna"
  printf 'RECOMMENDED_PROFILE=%q\n' "$recommended_profile"
  printf 'ROUTE_REASON=%q\n' "$route_reason"
  exit 0
fi

printf '{\n'
printf '  "cli": {"path": %s, "version": %s, "multi_agent": %s, "multi_agent_v2": %s, "luna": %s, "luna_max": %s},\n' \
  "$(printf '%s' "$cli_path" | json_escape)" \
  "$(printf '%s' "$cli_version" | json_escape)" \
  "$cli_multi_agent" "$cli_multi_agent_v2" "$cli_luna" "$cli_luna_max"
printf '  "app_cli": {"path": %s, "version": %s, "multi_agent": %s, "multi_agent_v2": %s, "luna": %s, "luna_max": %s},\n' \
  "$(printf '%s' "$app_path" | json_escape)" \
  "$(printf '%s' "$app_version" | json_escape)" \
  "$app_multi_agent" "$app_multi_agent_v2" "$app_luna" "$app_luna_max"
printf '  "native_v2_luna": %s,\n' "$(printf '%s' "$native_v2_luna" | json_escape)"
printf '  "recommended_profile": %s,\n' "$(printf '%s' "$recommended_profile" | json_escape)"
printf '  "fallback_model": "gpt-5.6-terra",\n'
printf '  "reason": %s\n' "$(printf '%s' "$route_reason" | json_escape)"
printf '}\n'
