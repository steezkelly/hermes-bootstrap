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
  assert_contains "$script" 'cp .*/system/nixos/harness\.nix .*/etc/nixos/harness\.nix'
  assert_contains "$script" 'cp -r .*/scripts/harness .*/etc/nixos/harness-scripts'
  assert_contains "$script" 'flake\.lock'
  assert_contains "$script" 'partition_path\(\)'
  assert_not_contains "$script" '\$\{TARGET_SSD\}[12]'
  assert_not_contains "$script" '\$\{ssd_dev\}[12]'
done

# The NixOS target creates and mounts an EFI system partition; the flake should
# install an x86_64 UEFI bootloader rather than an extlinux template.
assert_contains "$repo_root/system/nixos/flake.nix" 'boot\.loader\.systemd-boot\.enable = true;'
assert_contains "$repo_root/system/nixos/flake.nix" 'boot\.loader\.efi\.efiSysMountPoint = "/boot/efi";'
assert_contains "$repo_root/system/nixos/deployment-options.nix" 'adminInitialPassword = null;'
assert_contains "$repo_root/system/nixos/deployment-options.nix" 'adminAuthorizedKeys = \['
assert_contains "$repo_root/system/nixos/flake.nix" 'openssh\.authorizedKeys\.keys = deployment\.adminAuthorizedKeys;'
assert_contains "$repo_root/system/nixos/deployment-options.nix" 'consoleAutologin = true;'
assert_contains "$repo_root/system/nixos/deployment-options.nix" 'passwordlessSudo = true;'
assert_contains "$repo_root/system/nixos/flake.nix" 'lib\.optionalAttrs \(deployment\.adminInitialPassword != null\)'
assert_contains "$repo_root/system/nixos/flake.nix" 'initialPassword = deployment\.adminInitialPassword;'
assert_contains "$repo_root/system/nixos/flake.nix" 'services\.getty\.autologinUser = lib\.mkIf deployment\.consoleAutologin deployment\.adminUser;'
assert_contains "$repo_root/system/nixos/flake.nix" 'security\.sudo\.wheelNeedsPassword = !deployment\.passwordlessSudo;'
assert_contains "$repo_root/system/nixos/flake.nix" 'systemd\.services\.hermes-agent\.serviceConfig = \{'
assert_contains "$repo_root/system/nixos/flake.nix" 'UMask = "0007";'
assert_contains "$repo_root/system/nixos/flake.nix" 'terminal\.cwd = deployment\.workspaceDir;'
assert_contains "$repo_root/system/nixos/flake.nix" 'environment\.systemPackages = \['
assert_contains "$repo_root/system/nixos/flake.nix" '\] \+\+ import \./agent-extra-packages\.nix \{ inherit pkgs; \};'
assert_contains "$repo_root/system/nixos/flake.nix" 'system\.activationScripts\.hermesAdminStateAccess\.text'
assert_contains "$repo_root/system/nixos/flake.nix" 'ExecStartPost = "\+\$\{pkgs\.writeShellScript "hermes-agent-state-permissions-poststart"'
assert_contains "$repo_root/system/nixos/flake.nix" 'find \$\{deployment\.stateDir\}/\.hermes -type d -exec chmod 2770 \{\} \+'
assert_contains "$repo_root/system/nixos/flake.nix" 'find \$\{deployment\.stateDir\}/\.hermes -type f -exec chmod g\+rw,o-rwx \{\} \+'
assert_contains "$repo_root/system/nixos/flake.nix" './hermes-target-filesystems\.nix'
assert_contains "$repo_root/system/nixos/flake.nix" './harness\.nix'
assert_contains "$repo_root/system/nixos/hermes-target-filesystems.nix" 'checked-in default is intentionally empty'
assert_contains "$repo_root/scripts/deploy-hermes.sh" 'Target filesystem UUIDs: root=\$root_uuid efi=\$efi_uuid'
assert_contains "$repo_root/scripts/deploy-hermes.sh" 'patch_hermes_agent_cron_group_state "\$src_dir"'
assert_contains "$repo_root/scripts/deploy-hermes.sh" 'find_python\(\)'
assert_contains "$repo_root/scripts/deploy-hermes.sh" '/nix/store/\*python3\*/bin/python3\*'
assert_contains "$repo_root/scripts/deploy-hermes.sh" 'python_bin=\$\(find_python\)'
assert_contains "$repo_root/scripts/deploy-hermes.sh" 'os\.chmod\(path, 0o2770\)'
assert_contains "$repo_root/scripts/deploy-hermes.sh" 'os\.chmod\(path, 0o660\)'
assert_contains "$repo_root/scripts/deploy-hermes.sh" 'fileSystems\."/boot/efi"\.device = lib\.mkForce "/dev/disk/by-uuid/\$efi_uuid";'
assert_contains "$repo_root/scripts/deploy-hermes.sh" 'Keep the generated hermes-target-filesystems\.nix from above'
assert_contains "$repo_root/boot-image/overlay/auto-deploy.sh" 'cp .*/system/nixos/hermes-target-filesystems\.nix .*/etc/nixos/hermes-target-filesystems\.nix'
assert_contains "$repo_root/scripts/update-nixos-usb-autodeploy.sh" 'set default=2'
assert_contains "$repo_root/scripts/update-nixos-usb-autodeploy.sh" 'Reinstall \(DESTRUCTIVE\)'
assert_contains "$repo_root/scripts/update-nixos-usb-autodeploy.sh" 'Hermes Repair Installed System \(non-destructive\)'
assert_contains "$repo_root/scripts/update-nixos-usb-autodeploy.sh" 'repair-installed-hermes\.sh --auto-live'
assert_contains "$repo_root/scripts/repair-installed-hermes.sh" 'MESSAGING_CWD'
assert_contains "$repo_root/scripts/repair-installed-hermes.sh" 'Preserved existing /etc/nixos/\$file from installed target'
assert_contains "$repo_root/scripts/repair-installed-hermes.sh" 'authorized_keys'
assert_contains "$repo_root/scripts/repair-installed-hermes.sh" '10-hermes-admin-state\.conf'
assert_contains "$repo_root/scripts/repair-installed-hermes.sh" 'install_systemd_umask_dropin_if_possible'
assert_contains "$repo_root/scripts/repair-installed-hermes.sh" 'NixOS /etc/systemd may be read-only in this offline root'
assert_contains "$repo_root/scripts/repair-installed-hermes.sh" 'Continuing: state/config/SSH repair is complete'
assert_contains "$repo_root/scripts/repair-installed-hermes.sh" 'UMask=0007'
assert_contains "$repo_root/scripts/repair-installed-hermes.sh" 'ExecStartPost='
assert_contains "$repo_root/scripts/repair-installed-hermes.sh" 'find "\$state" -type d -exec chmod 2770'
assert_contains "$repo_root/scripts/repair-installed-hermes.sh" 'harness\.nix'
assert_contains "$repo_root/scripts/repair-installed-hermes.sh" 'harness-scripts'
assert_contains "$repo_root/scripts/repair-installed-hermes.sh" 'patch_hermes_agent_cron_group_state "\$target_nixos/hermes-agent-src"'
assert_contains "$repo_root/scripts/repair-installed-hermes.sh" 'find_python\(\)'
assert_contains "$repo_root/scripts/repair-installed-hermes.sh" '/nix/store/\*python3\*/bin/python3\*'
assert_contains "$repo_root/scripts/repair-installed-hermes.sh" 'python_bin=\$\(find_python\)'
assert_contains "$repo_root/scripts/repair-installed-hermes.sh" 'os\.chmod\(path, 0o2770\)'
assert_contains "$repo_root/scripts/repair-installed-hermes.sh" 'os\.chmod\(path, 0o660\)'
assert_contains "$repo_root/system/nixos/flake.nix" 'system\.stateVersion = "24\.05";'
assert_contains "$repo_root/README.md" 'docs/phase1-live-validation\.md'
assert_contains "$repo_root/docs/hardening-runbook.md" 'docs/phase1-live-validation\.md'
assert_contains "$repo_root/docs/phase1-live-validation.md" 'sudo systemctl start hermes-node-health-watchdog\.service'
assert_contains "$repo_root/docs/phase1-live-validation.md" 'sudo -u hermes-harness test ! -r /var/lib/hermes/secrets/hermes\.env'
assert_contains "$repo_root/docs/phase1-live-validation.md" 'NixOS 24\.05 support warning'
assert_contains "$repo_root/docs/phase1-live-validation.md" '/nix/store/\*python3\*/bin/python3\*'
assert_contains "$repo_root/docs/phase1-live-validation.md" 'Historical pre-fix events'
assert_contains "$repo_root/docs/phase1-live-validation.md" 'Only after this is stable should Phase 2 add push delivery'
assert_contains "$repo_root/README.md" 'docs/phase2-boundaries\.md'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'local artifacts remain the source of truth'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'raw journal export'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'static test proving no raw `/var/lib/hermes/secrets/hermes.env` dependency'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'hermes-phase2-delivery-brief-dry-run'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'systemctl status.*exit code 3'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'exclude boot-image'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'Recommended next live-send shape'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'send_delivery_brief\.py'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'email transport is not implemented'
assert_contains "$repo_root/system/nixos/harness.nix" 'hermes-phase2-delivery-brief-dry-run'
assert_not_contains "$repo_root/system/nixos/harness.nix" 'systemd\.timers\.hermes-phase2-delivery-brief'
assert_not_contains "$repo_root/system/nixos/flake.nix" 'generic-extlinux-compatible'

# Reproducible live testing should use a checked-in lock file.
[[ -s "$repo_root/system/nixos/flake.lock" ]] || {
  echo "Missing system/nixos/flake.lock" >&2
  exit 1
}
