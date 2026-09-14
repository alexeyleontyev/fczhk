#!/usr/bin/env sh
set -eu
# Destination should be an independently backed-up disk. Never overwrite an existing backup.
destination="${1:?Usage: sh scripts/backup.sh /absolute/path/to/backup-directory}"
mkdir -p "$destination"
backup_file="$destination/fczhk-$(date -u +%Y%m%dT%H%M%SZ).dump"
set -C
docker compose exec -T db pg_dump -U fczhk -d fczhk -Fc > "$backup_file"
docker compose exec -T db pg_restore --list < "$backup_file" > /dev/null
printf 'Backup created: %s\n' "$backup_file"
