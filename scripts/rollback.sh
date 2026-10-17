#!/usr/bin/env bash
# Code-only rollback. A changed schema requires the explicit recovery runbook.
set -euo pipefail
# shellcheck source=deploy/lib.sh
source "$(dirname "$0")/../deploy/lib.sh"
deployment_lock
target=$(cat .local/previous-image)
immutable_image "$target"
expected=$(cat .local/previous-revision)
current=$(compose exec -T db psql -U fczhk -d fczhk -Atc 'SELECT version_num FROM alembic_version')
[[ "$current" = "$expected" ]] || {
  echo 'Schema changed. Automatic code rollback refused; use docs/DEPLOYMENT_PLAN.md recovery procedure.' >&2; exit 1;
}
docker pull "$target"
export FCZHK_IMAGE="$target"
compose --profile polling stop app worker bot
trap 'compose --profile polling stop app worker bot || true; echo "Rollback failed; writers stopped. Inspect logs." >&2' ERR
compose up -d --wait --no-deps app worker proxy
compose exec -T app python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health/ready')"
printf '%s\n' "$target" > .local/release-image.next
mv .local/release-image.next .local/release-image
trap - ERR
echo "Rolled back to $target"
