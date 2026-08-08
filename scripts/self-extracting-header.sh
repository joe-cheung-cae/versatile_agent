#!/usr/bin/env bash
set -euo pipefail

archive_line="$(awk '/^__VERSATILE_ARCHIVE_BELOW__$/ { print NR + 1; exit }' "$0")"
if [[ -z "$archive_line" ]]; then
  printf 'Embedded archive marker was not found.\n' >&2
  exit 2
fi

extract_root="$(mktemp -d "${TMPDIR:-/tmp}/versatile-agent-installer.XXXXXX")"
trap 'rm -rf "$extract_root"' EXIT

embedded_archive="$extract_root/bundle.tar.gz"
tail -n "+$archive_line" "$0" > "$embedded_archive"

top_level=""
while IFS= read -r archive_entry; do
  case "$archive_entry" in
    /*|../*|*/../*|*/..|*\\*)
      printf 'Embedded archive contains an unsafe path: %s\n' "$archive_entry" >&2
      exit 2
      ;;
  esac
  entry_root="${archive_entry%%/*}"
  [[ -n "$entry_root" ]] || continue
  if [[ -z "$top_level" ]]; then
    top_level="$entry_root"
  elif [[ "$top_level" != "$entry_root" ]]; then
    printf 'Embedded archive contains more than one top-level path.\n' >&2
    exit 2
  fi
done < <(tar -tzf "$embedded_archive")

[[ -n "$top_level" ]] || { printf 'Embedded archive is empty.\n' >&2; exit 2; }
tar -xzf "$embedded_archive" -C "$extract_root"
bundle_dir="$extract_root/$top_level"
if [[ -z "$bundle_dir" || ! -x "$bundle_dir/install.sh" ]]; then
  printf 'Embedded bundle did not contain an executable install.sh.\n' >&2
  exit 2
fi

"$bundle_dir/install.sh" "$@"
exit $?

__VERSATILE_ARCHIVE_BELOW__
