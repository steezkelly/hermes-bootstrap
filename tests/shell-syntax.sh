#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

scripts=(
  "$repo_root/scripts/deploy-hermes.sh"
  "$repo_root/scripts/setup-hermes-agent.sh"
  "$repo_root/scripts/verify-bootstrap.sh"
  "$repo_root/boot-image/make-boot-image.sh"
  "$repo_root/boot-image/overlay/auto-deploy.sh"
  "$repo_root/boot-image/overlay/usr/local/bin/hw-detect"
  "$repo_root/boot-image/overlay/usr/local/bin/wifi-setup"
  "$repo_root/tests/deployment-readiness.sh"
)

for script in "${scripts[@]}"; do
  bash -n "$script"
done
