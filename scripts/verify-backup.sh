#!/usr/bin/env bash
# Full restore into a new disposable container; never connects to the live database.
set -euo pipefail
backup_file="${1:?Usage: bash scripts/verify-backup.sh /absolute/backup.dump}"
[[ "$backup_file" = /* ]] || { echo 'Use an absolute backup path.' >&2; exit 1; }
(cd "$(dirname "$backup_file")" && sha256sum --check "$(basename "$backup_file").sha256")
name="fczhk-restore-check-$(date +%s)-$$"
created=false
cleanup() { if $created; then docker rm -f "$name" > /dev/null; fi; }
trap cleanup EXIT
docker run -d --name "$name" --network none --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=restore postgres:17-alpine > /dev/null
created=true
ready=false
for _ in {1..60}; do
  # The entrypoint's temporary bootstrap server accepts only Unix sockets.
  if docker exec "$name" pg_isready -h 127.0.0.1 -U postgres -d restore > /dev/null 2>&1; then ready=true; break; fi
  sleep 1
done
if ! $ready; then docker logs "$name"; echo 'Restore PostgreSQL did not become ready.' >&2; exit 1; fi
docker exec -i "$name" pg_restore -h 127.0.0.1 -U postgres -d restore --exit-on-error --no-owner --no-acl < "$backup_file"
docker exec "$name" psql -h 127.0.0.1 -U postgres -d restore -v ON_ERROR_STOP=1 -c \
  'SELECT version_num FROM alembic_version; SELECT count(*) AS players FROM players; SELECT count(*) AS matches FROM matches;'
printf 'Full restore verified: %s\n' "$backup_file"
