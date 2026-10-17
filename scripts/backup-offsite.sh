#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=deploy/lib.sh
source "$(dirname "$0")/../deploy/lib.sh"
deployment_lock
: "${BACKUP_DIRECTORY:?Set an absolute BACKUP_DIRECTORY}"
: "${BACKUP_REMOTE:?Set an SSH rsync destination user@host:/absolute/directory}"
[[ "$BACKUP_REMOTE" =~ ^[a-zA-Z0-9_.-]+@[a-zA-Z0-9_.-]+:/[a-zA-Z0-9_./-]+$ ]] || {
  echo 'BACKUP_REMOTE must be user@host:/directory without spaces or shell metacharacters.' >&2; exit 1;
}
backup_file=$(bash scripts/backup.sh "$BACKUP_DIRECTORY")
bash scripts/verify-backup.sh "$backup_file"
# Host key must be provisioned; no insecure first-use acceptance.
rsync -a -e 'ssh -oBatchMode=yes -oStrictHostKeyChecking=yes' -- \
  "$backup_file" "$backup_file.sha256" "$BACKUP_REMOTE/"
date -u +%FT%TZ > .local/last-offsite-backup
printf 'Verified backup copied off this host: %s\n' "$backup_file"
