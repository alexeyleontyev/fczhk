#!/usr/bin/env bash
# Shared by host-side scripts. Run from the checked-out release directory.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p .local
if [[ -z "${FCZHK_IMAGE:-}" && -f .local/release-image ]]; then
  FCZHK_IMAGE=$(cat .local/release-image)
  export FCZHK_IMAGE
fi
compose() { docker compose --env-file .env "$@"; }
immutable_image() {
  [[ "$1" =~ @sha256:[a-f0-9]{64}$ || "$1" =~ :[a-f0-9]{40}$ ]] || {
    echo 'Use an image digest or a full 40-character Git SHA tag.' >&2; return 1;
  }
}
deployment_lock() {
  exec 9>.local/deploy.lock
  flock -n 9 || { echo 'Deployment, import or backup is already running.' >&2; exit 1; }
}
