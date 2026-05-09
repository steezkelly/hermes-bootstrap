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
assert_contains "$repo_root/README.md" 'docs/symbiosis-assimilation\.md'
assert_contains "$repo_root/docs/symbiosis-assimilation.md" 'Hermes-Symbiosis'
assert_contains "$repo_root/docs/symbiosis-assimilation.md" 'Coordinate -> reveal -> persist'
assert_contains "$repo_root/docs/symbiosis-assimilation.md" 'Do not import external orchestration code'
assert_contains "$repo_root/docs/symbiosis-assimilation.md" 'critical alert acknowledgement state'
assert_contains "$repo_root/docs/symbiosis-assimilation.md" 'No automatic delivery'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'local artifacts remain the source of truth'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'raw journal export'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'static test proving no raw `/var/lib/hermes/secrets/hermes.env` dependency'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'hermes-phase2-delivery-brief-dry-run'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'systemctl status.*exit code 3'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'exclude boot-image'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'Recommended next live-send shape'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'send_delivery_brief\.py'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'email transport is not implemented'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'Fail-closed manual-send live validation passed'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'Credential/transport decision boundary'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'no ready email transport'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'ntfy is the preferred first provider'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'no signup'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'HERMES_DELIVERY_NTFY_TOPIC'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'ntfy fail-closed live validation passed'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'First ntfy live-send gate'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'First ntfy live-send validation.*PASS'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'message appeared in ntfy history/UI'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'truncating the final two topic characters'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'ntfy receipt diagnostic gate'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'copying from wrapped terminal output'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'Poll/inspect ntfy history'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'rotate to a fresh high-entropy topic'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'Delivery dedupe/rate-limit state'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'delivery-state\.json'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'once-per-date'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'min-interval-seconds 82800'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'do not contact ntfy'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'unsafe path transitions'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'system.activationScripts.hermesHarnessDirectories'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'not `systemd.tmpfiles.rules`'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'timer must remain disabled by default'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'Strict delivery validation doctrine'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'one real delivery as the maximum normal validation budget'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'Failed sends must not write `last_success`'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'Critical alert candidate renderer'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'hermes-phase2-critical-alert-dry-run'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'no network transport'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'Critical alert acknowledgement/dedupe state'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'critical-alert-state\.json'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'condition_hash'
assert_contains "$repo_root/docs/phase2-boundaries.md" 'new, repeated/known, acknowledged, or expired'
assert_contains "$repo_root/system/nixos/harness.nix" 'hermes-phase2-delivery-brief-dry-run'
assert_contains "$repo_root/system/nixos/harness.nix" 'hermes-phase2-critical-alert-dry-run'
assert_contains "$repo_root/system/nixos/harness.nix" 'render_critical_alerts\.py --base'
assert_contains "$repo_root/system/nixos/harness.nix" 'state-dir.*delivery/state/alerts'
assert_contains "$repo_root/system/nixos/harness.nix" 'install -d -o hermes-harness -g hermes -m 2770 /var/lib/hermes/delivery/state/alerts'
assert_contains "$repo_root/system/nixos/harness.nix" 'ReadWritePaths = lib\.mkForce \[ "/var/lib/hermes/delivery/state/alerts" \];'
assert_not_contains "$repo_root/system/nixos/harness.nix" 'systemd\.timers\.hermes-phase2-critical-alert'
assert_contains "$repo_root/system/nixos/harness.nix" 'hermes-phase2-delivery-brief-send'
assert_contains "$repo_root/system/nixos/harness.nix" 'User = "hermes-delivery";'
assert_contains "$repo_root/system/nixos/harness.nix" 'transport ntfy'
assert_contains "$repo_root/system/nixos/harness.nix" 'state-dir.*delivery/state'
assert_contains "$repo_root/system/nixos/harness.nix" 'once-per-date'
assert_contains "$repo_root/system/nixos/harness.nix" 'min-interval-seconds 82800'
assert_contains "$repo_root/system/nixos/deployment-options.nix" 'phase2DeliveryTimerEnabled = false;'
assert_contains "$repo_root/system/nixos/deployment-options.nix" 'phase2DeliveryTimerCalendar = "\*-\*-\* 06:10:00";'
assert_contains "$repo_root/system/nixos/harness.nix" 'deployment = import ./deployment-options\.nix;'
assert_contains "$repo_root/system/nixos/harness.nix" 'systemd\.timers\.hermes-phase2-delivery-brief-send = lib\.mkIf deployment\.phase2DeliveryTimerEnabled'
assert_contains "$repo_root/system/nixos/harness.nix" 'OnCalendar = deployment\.phase2DeliveryTimerCalendar;'
assert_contains "$repo_root/system/nixos/harness.nix" 'Unit = "hermes-phase2-delivery-brief-send\.service";'
assert_contains "$repo_root/system/nixos/harness.nix" 'system\.activationScripts\.hermesHarnessDirectories'
assert_contains "$repo_root/system/nixos/harness.nix" 'deps = \[ "users" \];'
assert_contains "$repo_root/system/nixos/harness.nix" 'install -d -o hermes-delivery -g hermes -m 2770 /var/lib/hermes/delivery/state'
assert_not_contains "$repo_root/system/nixos/harness.nix" 'systemd\.tmpfiles\.rules'
assert_not_contains "$repo_root/system/nixos/flake.nix" 'generic-extlinux-compatible'

# Reproducible live testing should use a checked-in lock file.
[[ -s "$repo_root/system/nixos/flake.lock" ]] || {
  echo "Missing system/nixos/flake.lock" >&2
  exit 1
}
