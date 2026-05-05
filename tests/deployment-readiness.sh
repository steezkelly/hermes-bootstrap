#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

assert_contains() {
  local file="$1"
  local pattern="$2"
  if ! grep -Eq "$pattern" "$file"; then
    echo "Missing expected pattern in $file: $pattern" >&2
    exit 1
  fi
}

assert_not_contains() {
  local file="$1"
  local pattern="$2"
  if grep -Eq "$pattern" "$file"; then
    echo "Unexpected pattern in $file: $pattern" >&2
    exit 1
  fi
}

# The target /etc/nixos flake imports all of these local files; deployment
# scripts must copy them or live installation will fail after chrooting.
for script in \
  "$repo_root/scripts/deploy-hermes.sh" \
  "$repo_root/boot-image/overlay/auto-deploy.sh"; do
  assert_contains "$script" 'cp .*/system/nixos/flake\.nix .*/etc/nixos/flake\.nix'
  assert_contains "$script" 'cp .*/system/nixos/deployment-options\.nix .*/etc/nixos/deployment-options\.nix'
  assert_contains "$script" 'cp .*/system/nixos/agent-extra-packages\.nix .*/etc/nixos/agent-extra-packages\.nix'
  assert_contains "$script" 'flake\.lock'
  assert_contains "$script" 'partition_path\(\)'
  assert_not_contains "$script" '\$\{TARGET_SSD\}[12]'
  assert_not_contains "$script" '\$\{ssd_dev\}[12]'
done

# The NixOS target creates and mounts an EFI system partition; the flake should
# install an x86_64 UEFI bootloader rather than an extlinux template.
assert_contains "$repo_root/system/nixos/flake.nix" 'boot\.loader\.systemd-boot\.enable = true;'
assert_contains "$repo_root/system/nixos/flake.nix" 'boot\.loader\.efi\.efiSysMountPoint = "/boot/efi";'
assert_contains "$repo_root/system/nixos/flake.nix" 'system\.stateVersion = "24\.05";'
assert_not_contains "$repo_root/system/nixos/flake.nix" 'generic-extlinux-compatible'

# Reproducible live testing should use a checked-in lock file.
[[ -s "$repo_root/system/nixos/flake.lock" ]] || {
  echo "Missing system/nixos/flake.lock" >&2
  exit 1
}
