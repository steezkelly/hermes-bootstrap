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

for script in \
  "$repo_root/scripts/create-nixos-findiso-usb.sh" \
  "$repo_root/scripts/update-nixos-usb-autodeploy.sh"; do
  [[ -s "$script" ]] || { echo "Missing $script" >&2; exit 1; }

  # systemd-run-generator must see: systemd.run="/run/... args"
  # It must NOT see a surrounding single quote token on the generated linux
  # line, because that generates ExecStart="/run/... args" and systemd treats
  # the entire command string as the executable.
  assert_contains "$script" 'systemd\.run="/run/current-system/sw/bin/mkdir -p /run/hermes-usb"'
  assert_contains "$script" 'systemd\.run="/run/current-system/sw/bin/mount LABEL=NIXOS-BOOT /run/hermes-usb"'
  assert_contains "$script" 'systemd\.run="/run/current-system/sw/bin/env PATH=/run/current-system/sw/bin:/bin:/usr/bin /run/current-system/sw/bin/bash /run/hermes-usb/hermes-bootstrap/scripts/deploy-hermes\.sh --auto-live"'
  assert_contains "$script" 'systemd\.run="/run/current-system/sw/bin/env PATH=/run/current-system/sw/bin:/bin:/usr/bin /run/current-system/sw/bin/bash /run/hermes-usb/hermes-bootstrap/scripts/repair-installed-hermes\.sh --auto-live"'
  assert_contains "$script" 'Hermes Repair Installed System \(non-destructive\)'
  assert_contains "$script" '^set timeout=15$'
  assert_contains "$script" '^set default=2$'
  if grep -E '^[[:space:]]*linux ' "$script" | grep -q "'systemd.run="; then
    echo "Generated linux line in $script single-quotes systemd.run tokens" >&2
    exit 1
  fi
  if grep -E '^[[:space:]]*linux ' "$script" | grep -q 'HERMES_LIVE_TTY=1'; then
    echo "Generated linux line in $script bypasses openvt by setting HERMES_LIVE_TTY=1" >&2
    exit 1
  fi

  # The scripts should self-audit the generated grub.cfg using systemd's own
  # generator interface, not just grep for surface strings.
  assert_contains "$script" 'SYSTEMD_PROC_CMDLINE='
  assert_contains "$script" 'systemd-run-generator'
  assert_contains "$script" 'while IFS= read -r CMDLINE'
  assert_not_contains "$script" 'CMDLINE=.*head -1'
  assert_contains "$script" 'ExecStart=.*kernel-command-line\.service'
  assert_contains "$script" "'systemd.run="
done

# The live script must perform the interactive tty handoff itself. Setting
# HERMES_LIVE_TTY=1 in GRUB bypasses this guard and makes SSID reads EOF.
# It should attach to tty1 directly, not spawn openvt: openvt -w can return
# nonzero at console cleanup after the child succeeds.
assert_contains "$repo_root/scripts/deploy-hermes.sh" 'exec </dev/tty1 >/dev/tty1 2>&1'
assert_contains "$repo_root/scripts/deploy-hermes.sh" 'chvt 1'
assert_contains "$repo_root/scripts/deploy-hermes.sh" 'HERMES_LIVE_TTY:-0'
assert_not_contains "$repo_root/scripts/deploy-hermes.sh" 'openvt -sw'
assert_contains "$repo_root/scripts/deploy-hermes.sh" 'Using source passed by autodeploy'
assert_not_contains "$repo_root/scripts/deploy-hermes.sh" 'Looking for USB\.\.\.'
