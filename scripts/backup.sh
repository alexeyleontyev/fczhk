#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=deploy/lib.sh
source "$(dirname "$0")/../deploy/lib.sh"
umask 077
destination="${1:?Usage: bash scripts/backup.sh /absolute/backup-directory}"
[[ "$destination" = /* ]] || { echo 'Backup destination must be absolute.' >&2; exit 1; }
mkdir -p "$destination"
partial=$(mktemp "$destination/fczhk-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX.partial")
trap 'rm -f -- "$partial"' EXIT
compose exec -T db pg_dump -U fczhk -d fczhk -Fc > "$partial"
compose exec -T db pg_restore --list < "$partial" > /dev/null
backup_file="${partial%.partial}.dump"
mv -- "$partial" "$backup_file"
(cd "$destination" && sha256sum "$(basename "$backup_file")" > "$(basename "$backup_file").sha256")
printf '%s\n' "$backup_file"
