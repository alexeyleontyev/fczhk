#!/usr/bin/env bash
set -euo pipefail
# shellcheck source=deploy/lib.sh
source "$(dirname "$0")/../deploy/lib.sh"
compose "$@"
