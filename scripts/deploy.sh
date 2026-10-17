#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=deploy/lib.sh
source "$(dirname "$0")/../deploy/lib.sh"
target="${1:?Usage: bash scripts/deploy.sh ghcr.io/owner/repo:FULL_GIT_SHA}"
immutable_image "$target"
deployment_lock
docker pull "$target"
# Freeze the resolved registry content even if the operator supplied a SHA tag.
target=$(docker image inspect --format '{{index .RepoDigests 0}}' "$target")
immutable_image "$target"
export FCZHK_IMAGE="$target"
printf '%s\n' "$target" > .local/attempted-image
compose run --rm --no-deps tools python -c 'from fczhk.config import Settings; Settings()'
compose up -d --wait db
container=$(compose ps -q app)
if [[ -n "$container" ]]; then
  docker inspect --format '{{.Config.Image}}' "$container" > .local/previous-image
fi
# Stop all writers before the backup and migration, including optional polling.
compose --profile polling stop app worker bot
trap 'compose --profile polling stop app worker bot || true; echo "Release failed; writers stopped. Inspect logs and follow docs/DEPLOYMENT_PLAN.md." >&2' ERR
if compose exec -T db psql -U fczhk -d fczhk -Atc "SELECT to_regclass('public.alembic_version')" | grep -q alembic_version; then
  compose exec -T db psql -U fczhk -d fczhk -Atc 'SELECT version_num FROM alembic_version' > .local/previous-revision
  backup_file=$(bash scripts/backup.sh "${BACKUP_DIRECTORY:-$PWD/backups}")
  bash scripts/verify-backup.sh "$backup_file"
  printf '%s\n' "$backup_file" > .local/pre-release-backup
fi
compose run --rm migrate
compose up -d --wait --no-deps app worker proxy
compose exec -T app python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health/ready')"
printf '%s\n' "$target" > .local/release-image.next
mv .local/release-image.next .local/release-image
trap - ERR
printf 'Released and healthy: %s\n' "$target"
