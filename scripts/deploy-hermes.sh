#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# HERMES OS — Deploy Script
# ═══════════════════════════════════════════════════════════════════════════
# USB boot stick → NixOS installer → Internal SSD → Hermes Agent
#
# USAGE:
#   ./deploy-hermes.sh --prepare-usb /dev/sdX
#   ./deploy-hermes.sh --install /dev/nvme0n1
#   ./deploy-hermes.sh --all /dev/sdX /dev/nvme0n1
#
# PREREQUISITES (on host machine):
#   - NixOS 24.05 ISO: https://channels.nixos.org/nixos-24.05/latest-nixos-minimal-x86_64-linux.iso
#   - Ventoy: https://github.com/Ventoy/Ventoy/releases
#   - 226GB USB stick
#   - Target machine with 512GB internal SSD
#
set -euo pipefail

# ─── Colours ──────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'

log() { echo -e "${GREEN}[HERMES]${RESET} $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $*" >&2; }
error() { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }

need() { command -v "$1" &>/dev/null || error "Required: $1 (not found in PATH)"; }

# ─── Root check ────────────────────────────────────────────────────────────
check_root() {
  if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root (use sudo)"
  fi
}

# ─── Helpers ──────────────────────────────────────────────────────────────
confirm() {
  local prompt="${1:-Continue?}"
  local retries=3
  while (( retries-- > 0 )); do
    read -rp "$prompt [y/N] " answer
    case "${answer,,}" in
      y|yes) return 0 ;;
      n|no|"") return 1 ;;
      *) warn "Please answer yes or no" ;;
    esac
  done
  return 1
}

device_info() {
  local dev="$1"
  local size
  size=$(lsblk -d -o SIZE -n "$dev" 2>/dev/null | tr -d ' ')
  local model
  model=$(lsblk -d -o MODEL -n "$dev" 2>/dev/null | tr -d ' ')
  echo "Device: $dev  Size: $size  Model: $model"
}

# ═══════════════════════════════════════════════════════════════════════════
# STEP 1: Prepare USB stick
# ═══════════════════════════════════════════════════════════════════════════
prepare_usb() {
  local usb_dev="$1"

  check_root
  need lsblk parted mkfs.fat

  log "${BOLD}Preparing USB boot stick${RESET}"
  echo
  warn "ALL DATA ON $usb_dev WILL BE DESTROYED"
  device_info "$usb_dev"
  confirm "This is the correct device" || exit 1

  # Unmount any mounted partitions
  log "Unmounting existing partitions..."
  while IFS= read -r part; do
    local mp
    mp=$(findmnt -n -o TARGET "$part" 2>/dev/null || true)
    if [[ -n "$mp" ]]; then
      umount "$mp" 2>/dev/null || umount -l "$mp" 2>/dev/null || true
    fi
  done < <(lsblk -n -o NAME "$usb_dev" | grep -E '[0-9]$' | sed "s|^|${usb_dev}|")
  sync

  # Partition
  log "Creating GPT partition table..."
  parted -s "$usb_dev" -- mklabel gpt

  log "Creating 8GB FAT32 partition for Ventoy..."
  parted -s "$usb_dev" -- mkpart primary fat32 0% 8GB
  parted -s "$usb_dev" -- set 1 boot on 2>/dev/null || true  # legacy boot
  parted -s "$usb_dev" -- name 1 VENTOY

  # Format
  log "Formatting FAT32..."
  mkfs.fat -F 32 -n VENTOY "${usb_dev}1" >/dev/null

  # Install Ventoy (if ventoy2disk is available)
  if command -v ventoy2disk.sh &>/dev/null; then
    log "Installing Ventoy bootloader..."
    ventoy2disk.sh -i -s "$usb_dev" 2>&1 | grep -v "^Ventoy" || true
  else
    warn "Ventoy not installed — manual step required:"
    echo
    echo "  1. Download Ventoy from https://github.com/Ventoy/Ventoy/releases"
    echo "  2. Extract and run: sudo ./Ventoy2Disk.sh -i $usb_dev"
    echo "  3. Copy NixOS ISO to the VENTOY partition"
    echo
  fi

  # Mount and copy bootstrap
  log "Copying hermes-bootstrap to USB..."
  local mp
  mp=$(findmnt -n -o TARGET "${usb_dev}1" 2>/dev/null || echo "/mnt/ventoy")
  [[ -d "$mp" ]] || mkdir -p "$mp"
  mount "${usb_dev}1" "$mp" 2>/dev/null || mount "${usb_dev}1" "$mp" -o umask=0 || error "Cannot mount ${usb_dev}1"

  mkdir -p "$mp/hermes-bootstrap"
  cp -r "$(dirname "$0")/../"* "$mp/hermes-bootstrap/" 2>/dev/null || \
    cp -r . "$mp/hermes-bootstrap/"

  # Download/copy NixOS ISO prompt
  if [[ ! -f "$mp/NixOS-24.05-minimal.iso" ]]; then
    warn "NixOS ISO not found on USB — you need to copy it:"
    echo "  wget https://channels.nixos.org/nixos-24.05/latest-nixos-minimal-x86_64-linux.iso"
    echo "  cp NixOS-*.iso $mp/"
  fi

  sync
  umount "$mp"

  log "${GREEN}USB stick ready!${RESET}"
  log "Next: Boot target machine from USB, then run --install"
  echo
}

# ═══════════════════════════════════════════════════════════════════════════
# STEP 2: Partition internal SSD
# ═══════════════════════════════════════════════════════════════════════════
partition_internal() {
  local ssd_dev="$1"

  check_root

  log "${BOLD}Partitioning internal SSD${RESET}"
  echo
  warn "ALL DATA ON $ssd_dev WILL BE DESTROYED"
  device_info "$ssd_dev"
  confirm "This is the correct internal SSD" || exit 1

  # Unmount
  log "Unmounting..."
  while IFS= read -r part; do
    local mp
    mp=$(findmnt -n -o TARGET "$part" 2>/dev/null || true)
    if [[ -n "$mp" ]]; then
      umount "$mp" 2>/dev/null || umount -l "$mp" 2>/dev/null || true
    fi
  done < <(lsblk -n -o NAME "$ssd_dev" | grep -E '[0-9]$' | sed "s|^|${ssd_dev}|")

  # GPT
  log "Creating GPT..."
  parted -s "$ssd_dev" -- mklabel gpt

  # EFI (512MB)
  log "Creating EFI partition (512MB)..."
  parted -s "$ssd_dev" -- mkpart primary fat32 512MB 1024MB
  parted -s "$ssd_dev" -- set 1 esp on
  parted -s "$ssd_dev" -- name 1 EFI

  # Root (remaining space)
  log "Creating root partition..."
  parted -s "$ssd_dev" -- mkpart primary ext4 1024MB 100%
  parted -s "$ssd_dev" -- name 2 HERMES

  # Format
  log "Formatting EFI..."
  mkfs.fat -F 32 -n EFI "${ssd_dev}1" >/dev/null

  log "Formatting root..."
  mkfs.ext4 -L HERMES -E lazy_itable_init "${ssd_dev}2"

  log "${GREEN}Partitioning complete!${RESET}"
  echo
  echo "Partitions:"
  lsblk -o NAME,SIZE,FSTYPE,LABEL "$ssd_dev"
  echo
}

# ═══════════════════════════════════════════════════════════════════════════
# STEP 3: Bootstrap NixOS (runs inside NixOS installer)
# ═══════════════════════════════════════════════════════════════════════════
bootstrap_nixos() {
  local ssd_dev="$1"
  local bootstrap_src="${2:-/mnt/boot/ventoy/hermes-bootstrap}"

  check_root

  log "${BOLD}Bootstrapping NixOS${RESET}"

  # Detect partitions
  local efi_dev="${ssd_dev}1"
  local root_dev="${ssd_dev}2"

  log "Mounting root: $root_dev → /mnt"
  mount "$root_dev" /mnt

  log "Mounting EFI: $efi_dev → /mnt/boot/efi"
  mkdir -p /mnt/boot/efi
  mount "$efi_dev" /mnt/boot/efi

  # Copy bootstrap
  log "Copying hermes-bootstrap to /mnt/..."
  cp -r "$bootstrap_src" /mnt/ 2>/dev/null || error "Failed to copy bootstrap (is it mounted?)"

  # Generate hardware config
  log "Generating hardware config..."
  nixos-generate-config --root /mnt --force

  # Replace hardware config with our template
  if [[ -f /mnt/etc/nixos/hardware-configuration.nix ]]; then
    cp /mnt/etc/nixos/hardware-configuration.nix /mnt/etc/nixos/hardware-configuration.nix.bak
  fi

  # Use our hardware config
  cat > /mnt/etc/nixos/hardware-configuration.nix << HWEOF
# Hardware config — auto-generated and customized for Hermes OS
{ config, lib, pkgs, modulesPath, ... }:

{
  imports = [ (modulesPath + "/profiles/qemu-guest.nix") ];

  boot.initrd.availableKernelModules = [
    "ahci" "xhci_pci" "usb_storage" "nvme" "ext4" "vfat" "sr_mod" "sd_mod"
  ];

  fileSystems = {
    "/" = { device = "${root_dev}"; fsType = "ext4"; options = ["defaults" "noatime"]; };
    "/boot/efi" = { device = "${efi_dev}"; fsType = "vfat"; options = ["defaults"]; };
  };

  networking.useDHCP = lib.inNixShell;
  virtualisation.docker.enable = true;
}
HWEOF

  # Install hermes-agent flake
  local hermes_src="/mnt/hermes-bootstrap/system/nixos/hermes-agent-src"
  if [[ -d "$hermes_src" ]]; then
    log "Placing hermes-agent at /etc/nixos/hermes-agent..."
    mkdir -p /etc/nixos
    cp -r "$hermes_src" /etc/nixos/hermes-agent
  fi

  # Replace configuration.nix with our flake reference
  cat > /mnt/etc/nixos/configuration.nix << CFGEOF
# Hermes OS configuration
# Source: /mnt/hermes-bootstrap/system/nixos/flake.nix
# After install, this file lives at /etc/nixos/configuration.nix

(import /mnt/hermes-bootstrap/system/nixos/flake.nix).nixosConfigurations.hermes.config
CFGEOF

  # Run nixos-install
  log "Installing NixOS (this takes 10-30 minutes)..."
  nixos-install --no-root-password --flake "/mnt/hermes-bootstrap/system/nixos#hermes"

  # ── Post-install: seed secrets from USB ──────────────────────────────────
  log "Seeding secrets..."
  mkdir -p /mnt/var/lib/hermes/secrets
  chmod 0750 /mnt/var/lib/hermes/secrets

  # hermes.env from USB bootstrap data/secrets/ takes priority
  if [[ -f "$bootstrap_src/data/secrets/hermes.env" ]]; then
    cp "$bootstrap_src/data/secrets/hermes.env" /mnt/var/lib/hermes/secrets/hermes.env
    chmod 0640 /mnt/var/lib/hermes/secrets/hermes.env
    log "Seeded secrets from USB data/secrets/hermes.env"
  else
    # Create a placeholder that the agent can fill in post-boot
    cat > /mnt/var/lib/hermes/secrets/hermes.env << 'SECRETS_EOF'
# Secrets — fill in before first boot
# MINIMAX_API_KEY=***
SECRETS_EOF
    chmod 0640 /mnt/var/lib/hermes/secrets/hermes.env
    warn "No hermes.env found on USB — created placeholder at /var/lib/hermes/secrets/hermes.env"
  fi

  # Wire secrets into the flake's environmentFiles
  # (The flake references /var/lib/hermes/secrets/hermes.env via environmentFiles)

  # ── Post-install: init git repo for state tracking ───────────────────────
  log "Initializing git state tracking..."
  git -C /mnt/var/lib/hermes init
  git -C /mnt/var/lib/hermes config user.email "hermes@localhost"
  git -C /mnt/var/lib/hermes config user.name "Hermes OS"
  # Exclude secrets, volatile files, and db WAL/shm from git
  cat > /mnt/var/lib/hermes/.git/info/exclude << 'GITEXCL_EOF'
# Secrets — never commit these
secrets/
*.env
*.log
*.db-wal
*.db-shm
core.*
*.sock
.hermes/*.pid
GITEXCL_EOF

  log "${GREEN}NixOS installed!${RESET}"
  echo
  echo "Next steps:"
  echo "  1. Set root password: sudo chroot /mnt passwd"
  echo "  2. Unmount and reboot: sudo umount -R /mnt && sudo reboot"
  echo "  3. Remove USB stick after reboot"
  echo
}

# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════
usage() {
  cat << USAGE
${BOLD}Hermes OS Deploy Script${RESET}

${BOLD}USAGE:${RESET}
  $0 --prepare-usb /dev/sdX        Copy bootstrap + ISO onto a bootable USB
  $0 --partition /dev/nvme0n1       Partition internal SSD (interactive)
  $0 --bootstrap /dev/nvme0n1      Bootstrap NixOS (run from NixOS installer)
  $0 --all /dev/sdX /dev/nvme0n1   Full pipeline (prepare + partition + install)

${BOLD}NOTE:${RESET}
  Before --prepare-usb, make the USB bootable:
  - dd:  sudo dd if=nixos-*.iso of=/dev/sdX bs=4M status=progress conv=fsync
  - Ventoy: sudo ./Ventoy2Disk.sh -i /dev/sdX

${BOLD}EXAMPLES:${RESET}
  # Step 1: Make bootable USB (dd write)
  sudo dd if=latest-nixos-minimal-x86_64-linux.iso of=/dev/sdb bs=4M status=progress

  # Step 2: Copy bootstrap onto the now-bootable USB
  sudo $0 --prepare-usb /dev/sdb

  # On TARGET machine (booted from USB):
  sudo $0 --partition /dev/nvme0n1
  sudo $0 --bootstrap /dev/nvme0n1

${BOLD}WHAT IT DOES:${RESET}
  1. Mounts existing bootable USB → copies hermes-bootstrap + ISO to it
  2. Partitions internal SSD (EFI + root)
  3. Mounts SSD → copies bootstrap → runs nixos-install
  4. Installs hermes-agent via flake → seeds documents

${BOLD}POST-INSTALL:${RESET}
  After reboot:
    ssh hermes@hermes-node.local
    systemctl status hermes-agent
    hermes status

USAGE
}

main() {
  if [[ $# -eq 0 ]]; then
    usage; exit 0
  fi

  local cmd=""
  local arg1=""
  local arg2=""

  # Parse arguments
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --prepare-usb)
        cmd="prepare_usb"; arg1="$2"; shift 2 ;;
      --partition)
        cmd="partition_internal"; arg1="$2"; shift 2 ;;
      --bootstrap)
        cmd="bootstrap_nixos"; arg1="$2"; arg2="${3:-}"; shift 3 ;;
      --all)
        cmd="all"; arg1="$2"; arg2="$3"; shift 3 ;;
      --verify)
        cmd="verify"; arg1="$2"; shift 2 ;;
      --help|-h)
        usage; exit 0 ;;
      *)
        error "Unknown option: $1" ;;
    esac
  done

  case "$cmd" in
    prepare_usb)
      [[ -n "$arg1" ]] || { usage; exit 1; }
      prepare_usb "$arg1" ;;
    partition_internal)
      [[ -n "$arg1" ]] || { usage; exit 1; }
      partition_internal "$arg1" ;;
    bootstrap_nixos)
      [[ -n "$arg1" ]] || { usage; exit 1; }
      bootstrap_nixos "$arg1" "$arg2" ;;
    all)
      [[ -n "$arg1" && -n "$arg2" ]] || { usage; exit 1; }
      prepare_usb "$arg1"
      echo
      echo "=== USB ready. Boot target from USB, then run: ==="
      echo "sudo $0 --partition $arg2"
      echo "sudo $0 --bootstrap $arg2"
      echo ;;
    verify)
      log "Verification not yet implemented — PRs welcome" ;;
    *)
      usage; exit 1 ;;
  esac
}

main "$@"
