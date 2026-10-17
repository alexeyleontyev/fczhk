#!/usr/bin/env bash
# Exercise the exact image that CI will publish, against disposable PostgreSQL.
set -euo pipefail
image="${1:?Usage: bash scripts/smoke-image.sh IMAGE}"
prefix="fczhk-smoke-$(date +%s)-$$"
network="$prefix-net"
db="$prefix-db"
app="$prefix-app"
worker="$prefix-worker"
scratch=$(mktemp -d)
cleanup() {
  docker rm -f "$app" "$worker" "$db" > /dev/null 2>&1 || true
  docker network rm "$network" > /dev/null 2>&1 || true
  rm -rf -- "$scratch"
}
trap cleanup EXIT
docker network create "$network" > /dev/null
docker run -d --name "$db" --network "$network" --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_USER=fczhk -e POSTGRES_PASSWORD=smoke-only -e POSTGRES_DB=fczhk postgres:17-alpine > /dev/null
for _ in {1..60}; do
  if docker exec "$db" pg_isready -U fczhk > /dev/null 2>&1; then break; fi
  sleep 1
done
env_args=(--network "$network" -e FCZHK_ENV=test -e "FCZHK_DATABASE_URL=postgresql+psycopg://fczhk:smoke-only@$db/fczhk")
docker run --rm "${env_args[@]}" "$image" /app/.venv/bin/fczhk migrate
# A repeat migration must be harmless.
docker run --rm "${env_args[@]}" "$image" /app/.venv/bin/fczhk migrate
docker run --rm "$image" python scripts/import_history.py --help > /dev/null
docker run --rm "$image" python scripts/import_community_ratings.py --help > /dev/null
docker run --rm "$image" python -c "import json; from pathlib import Path; [json.loads(p.read_text()) for p in (Path('data/historical_import_corrections.json'), Path('data/community_rating_aliases.json'))]"
docker run -d --name "$app" "${env_args[@]}" "$image" > /dev/null
docker run -d --name "$worker" "${env_args[@]}" "$image" /app/.venv/bin/fczhk worker > /dev/null
healthy=false
for _ in {1..45}; do
  if docker exec "$app" python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health/ready')" > /dev/null 2>&1; then healthy=true; break; fi
  sleep 1
done
if ! $healthy; then docker logs "$app"; docker logs "$worker"; exit 1; fi
docker exec "$app" python -c "import urllib.request; assert b'<html' in urllib.request.urlopen('http://localhost:8000/').read()"
docker exec "$db" psql -U fczhk -d fczhk -v ON_ERROR_STOP=1 -c "INSERT INTO players (alias, merged_into, telegram_id, created_at) VALUES ('Restore sentinel', NULL, 1234, now())" > /dev/null
docker exec "$db" pg_dump -U fczhk -d fczhk -Fc > "$scratch/smoke.dump"
(cd "$scratch" && sha256sum smoke.dump > smoke.dump.sha256)
bash scripts/verify-backup.sh "$scratch/smoke.dump"
docker stop --time 5 "$worker" "$app" > /dev/null
for container in "$worker" "$app"; do
  code=$(docker inspect --format '{{.State.ExitCode}}' "$container")
  [[ "$code" == 0 ]] || { echo "$container shutdown failed: exit $code" >&2; exit 1; }
done
echo "Image smoke, restore and graceful shutdown passed: $image"
