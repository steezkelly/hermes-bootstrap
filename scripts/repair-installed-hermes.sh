#!/usr/bin/env bash
# Non-destructive repair for an already-installed Hermes NixOS node.
# Fixes shared Hermes state permissions, removes deprecated MESSAGING_CWD,
# writes terminal.cwd into config.yaml, and adds a systemd drop-in that keeps
# service-created Hermes state group-readable after restarts.
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; RESET='\033[0m'
log() { echo -e "${GREEN}[REPAIR]${RESET} $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $*"; }
fail() { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }

MODE="installed"
TARGET_ROOT=""
NO_REBOOT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --auto-live) MODE="live"; shift ;;
    --root) TARGET_ROOT="${2:-}"; shift 2 ;;
    --no-reboot) NO_REBOOT=1; shift ;;
    *) fail "unknown argument: $1" ;;
  esac
done

[[ $EUID -eq 0 ]] || fail "run as root: sudo $0"

is_installed_root() {
  local root="$1"
  [[ -d "$root/var/lib/hermes/.hermes" ]] && { [[ -f "$root/etc/NIXOS" ]] || [[ -d "$root/etc/nixos" ]]; }
}

find_installed_root() {
  if [[ -n "$TARGET_ROOT" ]]; then
    is_installed_root "$TARGET_ROOT" || fail "not a Hermes NixOS root: $TARGET_ROOT"
    printf '%s\n' "$TARGET_ROOT"
    return 0
  fi

  if is_installed_root /; then
    printf '/\n'
    return 0
  fi

  for candidate in /mnt /mnt/hermes-installed /run/hermes-installed; do
    if is_installed_root "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  mkdir -p /mnt/hermes-installed
  while IFS= read -r part; do
    [[ -b "$part" ]] || continue
    if mountpoint -q /mnt/hermes-installed; then
      umount /mnt/hermes-installed 2>/dev/null || true
    fi
    if mount -o rw "$part" /mnt/hermes-installed 2>/dev/null; then
      if is_installed_root /mnt/hermes-installed; then
        printf '/mnt/hermes-installed\n'
        return 0
      fi
      umount /mnt/hermes-installed 2>/dev/null || true
    fi
  done < <(lsblk -rpo NAME,FSTYPE,TYPE,TRAN 2>/dev/null | awk '$3=="part" && $4!="usb" && ($2=="ext4" || $2=="btrfs" || $2=="xfs") {print $1}')

  fail "could not find installed Hermes NixOS root"
}

backup_file() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  local stamp
  stamp=$(date +%Y%m%d_%H%M%S)
  cp -a "$file" "$file.bak.$stamp"
  log "Backed up ${file} -> ${file}.bak.${stamp}"
}

set_terminal_cwd_yaml() {
  local config="$1"
  local cwd="$2"
  mkdir -p "$(dirname "$config")"
  if [[ ! -f "$config" ]]; then
    cat > "$config" <<EOF
terminal:
  cwd: $cwd
EOF
    return 0
  fi

  awk -v cwd="$cwd" '
    BEGIN { in_terminal=0; saw_terminal=0; wrote_cwd=0 }
    /^terminal:[[:space:]]*$/ {
      if (in_terminal && !wrote_cwd) print "  cwd: " cwd
      print
      in_terminal=1; saw_terminal=1; wrote_cwd=0
      next
    }
    in_terminal && /^[^[:space:]#][^:]*:/ {
      if (!wrote_cwd) print "  cwd: " cwd
      in_terminal=0
    }
    in_terminal && /^[[:space:]]+cwd:[[:space:]]*/ {
      print "  cwd: " cwd
      wrote_cwd=1
      next
    }
    { print }
    END {
      if (in_terminal && !wrote_cwd) print "  cwd: " cwd
      if (!saw_terminal) {
        print "terminal:"
        print "  cwd: " cwd
      }
    }
  ' "$config" > "$config.tmp"
  mv "$config.tmp" "$config"
}

copy_nixos_sources_if_available() {
  local root="$1"
  local src=""
  for candidate in \
    /run/hermes-usb/hermes-bootstrap/system/nixos \
    "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)/system/nixos"; do
    if [[ -f "$candidate/flake.nix" ]]; then
      src="$candidate"
      break
    fi
  done
  [[ -n "$src" ]] || { warn "No bootstrap system/nixos source found; skipping /etc/nixos refresh."; return 0; }

  mkdir -p "$root/etc/nixos"
  for file in flake.nix deployment-options.nix agent-extra-packages.nix hermes-target-filesystems.nix harness.nix flake.lock; do
    [[ -f "$src/$file" ]] || continue

    # The installed target's hermes-target-filesystems.nix is generated from the
    # real internal SSD UUIDs during deployment. The checked-in repo copy is an
    # intentionally empty placeholder. A repair path must never clobber known-good
    # target filesystem bindings with that placeholder, or the next rebuild could
    # regress back toward USB-derived filesystem state.
    if [[ "$file" == "hermes-target-filesystems.nix" ]] \
      && [[ -f "$root/etc/nixos/$file" ]] \
      && grep -q 'checked-in default is intentionally empty' "$src/$file"; then
      log "Preserved existing /etc/nixos/$file from installed target"
      continue
    fi

    cp -a "$src/$file" "$root/etc/nixos/$file"
    log "Updated /etc/nixos/$file from bootstrap repo"
  done

  if [[ -d "$(dirname "$src")/../scripts/harness" ]]; then
    rm -rf "$root/etc/nixos/harness-scripts"
    cp -a "$(dirname "$src")/../scripts/harness" "$root/etc/nixos/harness-scripts"
    log "Updated /etc/nixos/harness-scripts from bootstrap repo"
  elif [[ -d "$src/harness-scripts" ]]; then
    rm -rf "$root/etc/nixos/harness-scripts"
    cp -a "$src/harness-scripts" "$root/etc/nixos/harness-scripts"
    log "Updated /etc/nixos/harness-scripts from bootstrap repo"
  else
    warn "No harness script source found; keeping existing /etc/nixos/harness-scripts if present."
  fi

  # deploy-hermes.sh rewrites the target flake to use the staged local
  # hermes-agent source and removes the upstream GitHub lock. A later repair that
  # refreshes flake.nix from the repo must preserve that deploy-time invariant;
  # otherwise nixos-rebuild can fetch upstream and hit known npm-deps hash drift.
  local target_nixos="$root/etc/nixos"
  local old_hash="sha256-a/HGI9OgVcTnZrMXA7xFMGnFoVxyHe95fulVz+WNYB0="
  local new_hash="sha256-MLcLhjTF6dgdvNBtJWzo8Nh19eNh/ZitD2b07nm61Tc="
  if [[ -f "$target_nixos/hermes-agent-src/flake.nix" ]]; then
    if grep -q 'hermes-agent.url = "github:NousResearch/hermes-agent";' "$target_nixos/flake.nix"; then
      sed -i 's#hermes-agent.url = "github:NousResearch/hermes-agent";#hermes-agent.url = "path:./hermes-agent-src";#' "$target_nixos/flake.nix"
      rm -f "$target_nixos/flake.lock"
      log "Preserved local hermes-agent-src flake input for rebuild stability"
    fi
    if [[ -f "$target_nixos/hermes-agent-src/nix/tui.nix" ]] && grep -q "$old_hash" "$target_nixos/hermes-agent-src/nix/tui.nix"; then
      sed -i "s#${old_hash}#${new_hash}#" "$target_nixos/hermes-agent-src/nix/tui.nix"
      rm -f "$target_nixos/flake.lock"
      log "Patched staged hermes-agent TUI npmDeps hash"
    fi
  else
    warn "No /etc/nixos/hermes-agent-src found; leaving hermes-agent input as declared in refreshed flake."
  fi
}

install_admin_ssh_keys_if_available() {
  local root="$1"
  local prefix="$root"
  [[ "$root" == "/" ]] && prefix=""
  local options="$prefix/etc/nixos/deployment-options.nix"
  [[ -f "$options" ]] || { warn "No deployment-options.nix found; skipping admin SSH key install."; return 0; }

  local keys
  keys=$(sed -nE 's/^[[:space:]]*"((ssh-(ed25519|rsa)|ecdsa-sha2-nistp[0-9]+) [^"]+)";?[[:space:]]*$/\1/p' "$options" || true)
  [[ -n "$keys" ]] || { warn "No adminAuthorizedKeys found; skipping admin SSH key install."; return 0; }

  local uid gid home ssh_dir auth_file
  uid=$(awk -F: '$1=="hermes-admin" {print $3}' "$prefix/etc/passwd" 2>/dev/null | head -1 || true)
  gid=$(awk -F: '$1=="hermes-admin" {print $4}' "$prefix/etc/passwd" 2>/dev/null | head -1 || true)
  home="$prefix/home/hermes-admin"
  ssh_dir="$home/.ssh"
  auth_file="$ssh_dir/authorized_keys"
  mkdir -p "$ssh_dir"
  touch "$auth_file"

  while IFS= read -r key; do
    [[ -n "$key" ]] || continue
    if ! grep -Fxq "$key" "$auth_file"; then
      printf '%s\n' "$key" >> "$auth_file"
      log "Installed admin SSH key: ${key##* }"
    fi
  done <<< "$keys"

  chmod 700 "$ssh_dir"
  chmod 600 "$auth_file"
  if [[ -n "$uid" && -n "$gid" ]]; then
    chown -R "$uid:$gid" "$ssh_dir" || true
  fi
}

install_systemd_umask_dropin_if_possible() {
  local root="$1"
  local state="$2"
  local gid="$3"
  local prefix="$root"
  [[ "$root" == "/" ]] && prefix=""
  local dropin_dir="$prefix/etc/systemd/system/hermes-agent.service.d"
  local dropin_file="$dropin_dir/10-hermes-admin-state.conf"

  # On an offline NixOS root, /etc/systemd/system can be a symlink into the
  # generation's read-only /etc/static tree. The immediate repair must not abort
  # after state/config/SSH have been fixed just because an imperative drop-in is
  # impossible there. The durable setting is also copied into /etc/nixos/flake.nix
  # and can be activated after SSH works with nixos-rebuild.
  if ! mkdir -p "$dropin_dir" 2>/dev/null; then
    warn "Could not create $dropin_dir; NixOS /etc/systemd may be read-only in this offline root."
    warn "Continuing: state/config/SSH repair is complete, and /etc/nixos/flake.nix carries UMask=0007 for the next rebuild."
    return 0
  fi

  if ! cat > "$dropin_file" <<EOF
[Service]
UMask=0007
ExecStartPost=+/bin/sh -c 'sleep 5; if [ -d "$state" ]; then chgrp -R "$gid" "$state" || true; find "$state" -type d -exec chmod 2770 {} + || true; find "$state" -type f -exec chmod g+rw,o-rwx {} + || true; fi'
EOF
  then
    warn "Could not write $dropin_file; continuing with declarative /etc/nixos UMask=0007 fix only."
    return 0
  fi
  log "Installed systemd admin-state permissions drop-in for hermes-agent.service"
}

repair_root() {
  local root="$1"
  local prefix="$root"
  [[ "$root" == "/" ]] && prefix=""

  local state="$prefix/var/lib/hermes/.hermes"
  local workspace="$prefix/var/lib/hermes/workspace"
  local env_file="$state/.env"
  local config_file="$state/config.yaml"

  [[ -d "$state" ]] || fail "missing Hermes state dir: $state"
  mkdir -p "$workspace"

  local uid gid admin_gid
  uid=$(awk -F: '$1=="hermes" {print $3}' "$prefix/etc/passwd" 2>/dev/null | head -1 || true)
  gid=$(awk -F: '$1=="hermes" {print $3}' "$prefix/etc/group" 2>/dev/null | head -1 || true)
  admin_gid=$(awk -F: '$1=="hermes-admin" {print $4}' "$prefix/etc/passwd" 2>/dev/null | head -1 || true)
  [[ -n "$gid" ]] || fail "could not find hermes group in $prefix/etc/group"

  log "Fixing group-readable Hermes state permissions"
  chown -R ":$gid" "$state"
  find "$state" -type d -exec chmod 2770 {} +
  find "$state" -type f -exec chmod g+rw,o-rwx {} +
  if [[ -n "$uid" ]]; then
    chown -R "$uid:$gid" "$workspace" || true
  else
    chown -R ":$gid" "$workspace" || true
  fi
  chmod 2770 "$workspace"

  if [[ -f "$env_file" ]] && grep -q '^MESSAGING_CWD=' "$env_file"; then
    backup_file "$env_file"
    grep -v '^MESSAGING_CWD=' "$env_file" > "$env_file.tmp"
    mv "$env_file.tmp" "$env_file"
    chown ":$gid" "$env_file"
    chmod g+rw,o-rwx "$env_file"
    log "Removed deprecated MESSAGING_CWD from $env_file"
  else
    log "No deprecated MESSAGING_CWD line found"
  fi

  backup_file "$config_file"
  set_terminal_cwd_yaml "$config_file" "/var/lib/hermes/workspace"
  chown ":$gid" "$config_file"
  chmod g+rw,o-rwx "$config_file"
  log "Set terminal.cwd in $config_file"

  copy_nixos_sources_if_available "$root"
  install_admin_ssh_keys_if_available "$root"
  install_systemd_umask_dropin_if_possible "$root" "$state" "$gid"

  if [[ "$root" == "/" ]]; then
    log "Reloading systemd and restarting hermes-agent.service"
    systemctl daemon-reload || true
    systemctl restart hermes-agent || true
    systemctl --no-pager --full status hermes-agent | sed -n '1,25p' || true
    if command -v hermes >/dev/null 2>&1; then
      log "Hermes status after repair:"
      sudo -u hermes-admin env HERMES_HOME=/var/lib/hermes/.hermes hermes status 2>&1 | sed -n '1,80p' || true
    fi
  else
    log "Offline root repaired at $root"
    log "Reboot into the internal SSD for the systemd drop-in and config cleanup to take effect."
  fi
}

ROOT=$(find_installed_root)
log "Repair target root: $ROOT"
repair_root "$ROOT"

if [[ "$MODE" == "live" && -z "$NO_REBOOT" ]]; then
  log "Live repair complete. Rebooting in 10 seconds..."
  sleep 10
  reboot || true
fi

log "Repair complete."
