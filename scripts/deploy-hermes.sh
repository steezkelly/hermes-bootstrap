#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# HERMES OS — Deploy Script  (v2)
# ═══════════════════════════════════════════════════════════════════════════
# USB boot stick → NixOS installer → Internal SSD → Hermes Agent
#
# USAGE:
#   ./deploy-hermes.sh --prepare-usb /dev/sdX           Prepare bootable USB
#   ./deploy-hermes.sh --partition /dev/nvme0n1         Partition internal SSD
#   ./deploy-hermes.sh --bootstrap /dev/nvme0n1        Bootstrap NixOS
#   ./deploy-hermes.sh --all /dev/sdX /dev/nvme0n1     Full pipeline
#
# PREREQUISITES (on host machine):
#   - NixOS 24.05 ISO: https://channels.nixos.org/nixos-24.05/latest-nixos-minimal-x86_64-linux.iso
#   - hermes-boot.img (built by boot-image/make-boot-image.sh)
#   - USB stick (target machine)
#   - Target machine with internal SSD
#
set -euo pipefail

# ─── Colours ──────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'

log() { echo -e "${GREEN}[HERMES]${RESET} $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $*" >&2; }
error() { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }

need() { command -v "$1" &>/dev/null || error "Required: $1 (not found in PATH)"; }

partition_path() {
  local disk="$1"
  local part_num="$2"

  # NVMe/MMC-style disks end in a digit and require a 'p' separator
  # (/dev/nvme0n1p1, /dev/mmcblk0p1). sdX-style disks do not.
  case "$disk" in
    *[0-9]) printf '%sp%s\n' "$disk" "$part_num" ;;
    *) printf '%s%s\n' "$disk" "$part_num" ;;
  esac
}

list_partition_paths() {
  local disk="$1"
  lsblk -ln -o PATH "$disk" 2>/dev/null | tail -n +2
}

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

# ─── Hardware Detection ──────────────────────────────────────────────────
hardware_detect() {
  local label="${1:-=== Hardware Detection ===}"
  echo ""
  log "${BOLD}${label}${RESET}"
  echo ""
  echo "Block devices:"
  lsblk -o NAME,SIZE,TYPE,TRAN,MODEL,UUID 2>/dev/null | grep -v 'NAME' | head -20
  echo ""
  echo "Network interfaces:"
  ip -br link show 2>/dev/null | grep -v 'UNKNOWN' || ip link show 2>/dev/null | grep -E '^[0-9]+:|ether'
  echo ""
  echo "IP addresses:"
  ip addr show 2>/dev/null | grep -E 'inet ' | awk '{print "  "$2}' || echo "  (none)"
  echo ""
  if command -v iw &>/dev/null; then
    echo "Wireless devices:"
    iw dev 2>/dev/null | grep -E 'Interface|ssid' | paste - - 2>/dev/null || echo "  (none)"
    echo ""
  fi
  echo "CPU: $(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2 | sed 's/^ *//' || echo 'unknown')"
  echo "RAM: $(grep MemTotal /proc/meminfo 2>/dev/null | awk '{printf "%.1f GB", $2/1024/1024}')"
  echo ""
}

# ─── USB I/O Retry Mount ─────────────────────────────────────────────────
# Try to mount a USB device with retries and fallback mount options.
# Usage: usb_mount "/dev/sdX1" "/mnt/point"
usb_mount_retry() {
  local dev="$1"
  local mp="$2"
  local retries="${3:-3}"
  local options="ro"

  mkdir -p "$mp"

  while (( retries-- > 0 )); do
    if mount -o "$options" "$dev" "$mp" 2>/dev/null; then
      return 0
    fi
    warn "Mount failed (attempt $((3 - retries))/3). Retrying..."
    sleep 2
  done

  # Fallback: try sync mode (slower but more reliable on weak USB)
  warn "Standard mount failed. Trying sync mode..."
  if mount -o sync,"$options" "$dev" "$mp" 2>/dev/null; then
    warn "Mounted in sync mode (slow but reliable)"
    return 0
  fi

  # Fallback: try with errors=remount-ro
  if mount -o errors=remount-ro,"$options" "$dev" "$mp" 2>/dev/null; then
    return 0
  fi

  return 1
}

# ─── WiFi Setup ──────────────────────────────────────────────────────────
# Auto-detect WiFi interface and bring up network with guided fallback.
wifi_setup() {
  local max_wait="${1:-5}"

  # Find wireless interface
  local wlan_iface
  wlan_iface=$(iw dev 2>/dev/null | grep Interface | awk '{print $2}' | head -1 || true)

  # Try ethernet DHCP first
  local eth_iface
  eth_iface=$(ip -br link show 2>/dev/null | grep -oE 'eth[0-9]+|enp[0-9]+s[0-9]+' | head -1 || true)
  if [[ -n "$eth_iface" ]]; then
    log "Trying ethernet ($eth_iface)..."
    dhcpcd "$eth_iface" 2>/dev/null || dhcpcd -q "$eth_iface" 2>/dev/null || true
    sleep 2
    if ping -c 1 -W 3 8.8.8.8 &>/dev/null; then
      log "Ethernet OK — internet reachable."
      return 0
    fi
  fi

  # No ethernet — must use WiFi
  if [[ -z "$wlan_iface" ]]; then
    # Try to bring it up anyway (some adapters show as wlan by default)
    ip link set wlan0 up 2>/dev/null || true
    wlan_iface=$(iw dev 2>/dev/null | grep Interface | awk '{print $2}' | head -1 || true)
  fi

  if [[ -z "$wlan_iface" ]]; then
    warn "No wireless interface found. Skipping WiFi."
    return 1
  fi

  log "Wireless interface: $wlan_iface"

  # Try saved wpa_supplicant.conf
  if [[ -f /etc/wpa_supplicant.conf ]] && grep -q 'ssid=' /etc/wpa_supplicant.conf 2>/dev/null; then
    log "Trying saved WiFi config..."
    wpa_supplicant -B -i "$wlan_iface" -c /etc/wpa_supplicant.conf 2>/dev/null && {
      dhcpcd -q "$wlan_iface" 2>/dev/null || true
      sleep "$max_wait"
      if ping -c 1 -W 3 8.8.8.8 &>/dev/null; then
        log "WiFi OK — internet reachable."
        return 0
      fi
    }
  fi

  # Guided setup
  echo ""
  warn "No saved WiFi config. Running guided setup..."
  echo ""
  echo "Available networks on $wlan_iface:"
  iw dev "$wlan_iface" scan 2>/dev/null | grep -E 'SSID:|signal:' | paste - - 2>/dev/null || echo "  (scan failed)"
  echo ""

  local ssid=""
  local password=""

  printf 'SSID: '
  read -r ssid

  if [[ -z "$ssid" ]]; then
    warn "No SSID entered. Skipping WiFi."
    return 1
  fi

  printf 'Password (leave blank for open network): '
  read -r password

  if [[ -n "$password" ]]; then
    wpa_passphrase "$ssid" "$password" > /etc/wpa_supplicant.conf
  else
    printf 'network={\n  ssid="%s"\n  key_mgmt=NONE\n}\n' "$ssid" > /etc/wpa_supplicant.conf
  fi

  log "Starting wpa_supplicant on $wlan_iface..."
  wpa_supplicant -B -i "$wlan_iface" -c /etc/wpa_supplicant.conf 2>/dev/null || {
    warn "wpa_supplicant failed. Check dmesg for driver issues."
    return 1
  }

  dhcpcd -q "$wlan_iface" 2>/dev/null || true
  sleep "$max_wait"

  if ping -c 1 -W 5 8.8.8.8 &>/dev/null; then
    log "WiFi OK — internet reachable."
    return 0
  else
    warn "WiFi connected but internet unreachable. Check router settings."
    return 1
  fi
}

# ═══════════════════════════════════════════════════════════════════════════
# STEP 1: Prepare USB stick
# ═══════════════════════════════════════════════════════════════════════════
prepare_usb() {
  local usb_dev="$1"

  check_root
  need lsblk parted mkfs.fat

  log "${BOLD}Preparing USB boot stick (v2 — no Ventoy)${RESET}"
  echo ""
  hardware_detect "USB Preparation"
  echo ""
  warn "ALL DATA ON $usb_dev WILL BE DESTROYED"
  device_info "$usb_dev"
  confirm "This is the correct USB device" || exit 1

  # Unmount any mounted partitions
  log "Unmounting existing partitions..."
  while IFS= read -r part; do
    local mp
    mp=$(findmnt -n -o TARGET "$part" 2>/dev/null || true)
    if [[ -n "$mp" ]]; then
      umount "$mp" 2>/dev/null || umount -l "$mp" 2>/dev/null || true
    fi
  done < <(list_partition_paths "$usb_dev")
  sync

  # ── v2: Single FAT32 partition (no Ventoy) ───────────────────────────────
  log "Creating FAT32 partition..."
  parted -s "$usb_dev" -- mklabel gpt
  parted -s "$usb_dev" -- mkpart primary fat32 0% 100%
  parted -s "$usb_dev" -- set 1 boot on 2>/dev/null || true
  parted -s "$usb_dev" -- name 1 HERMES-DATA

  local usb_part
  usb_part=$(partition_path "$usb_dev" 1)

  log "Formatting FAT32..."
  mkfs.fat -F 32 -n HERMES-DATA "$usb_part" >/dev/null

  # Mount
  local mp
  mp=$(findmnt -n -o TARGET "$usb_part" 2>/dev/null || echo "/mnt/usb")
  [[ -d "$mp" ]] || mkdir -p "$mp"
  mount "$usb_part" "$mp" 2>/dev/null || mount "$usb_part" "$mp" -o umask=0 || error "Cannot mount $usb_part"

  # Copy hermes-bootstrap repo
  log "Copying hermes-bootstrap to USB..."
  mkdir -p "$mp/hermes-bootstrap"
  cp -r "$(dirname "$0")/../"* "$mp/hermes-bootstrap/" 2>/dev/null || \
    cp -r . "$mp/hermes-bootstrap/"

  # Check for hermes-agent-src (must be pre-bundled)
  if [[ ! -d "$mp/hermes-bootstrap/system/nixos/hermes-agent-src" ]]; then
    warn "hermes-agent-src not found in repo!"
    warn "Run this BEFORE prepare-usb:"
    echo "  ./scripts/setup-hermes-agent.sh --copy ~/.hermes/hermes-agent"
    echo ""
    warn "Copy hermes-agent source into the repo now:"
    printf '  cp -r ~/.hermes/hermes-agent "$USB_MOUNT/hermes-bootstrap/system/nixos/hermes-agent-src"\n'
    echo ""
    if [[ -t 0 ]]; then
      printf 'Press Enter when done, or Ctrl+C to abort... '
      read -r
    fi
  fi

  # Copy NixOS ISO if present locally. Prefer an explicit env var so this
  # public script is not tied to one operator's home directory.
  local iso_source="${NIXOS_ISO:-}"
  if [[ -z "$iso_source" ]]; then
    for candidate in \
      "$(pwd)/latest-nixos-minimal-x86_64-linux.iso" \
      "$(pwd)/NixOS-24.05-minimal.iso" \
      "$HOME/latest-nixos-minimal-x86_64-linux.iso" \
      "$HOME/Downloads/latest-nixos-minimal-x86_64-linux.iso"; do
      if [[ -f "$candidate" ]]; then
        iso_source="$candidate"
        break
      fi
    done
  fi

  if [[ -n "$iso_source" ]] && [[ -f "$iso_source" ]] && [[ ! -f "$mp/NixOS-24.05-minimal.iso" ]]; then
    log "Copying NixOS ISO to USB (this may take several minutes)..."
    cp "$iso_source" "$mp/NixOS-24.05-minimal.iso"
  elif ! compgen -G "$mp/NixOS-*.iso" >/dev/null && ! compgen -G "$mp/nixos-*.iso" >/dev/null; then
    warn "NixOS ISO not found on USB or locally."
    echo "  Download: wget -O \"$mp/NixOS-24.05-minimal.iso\" \\"
    echo "    https://channels.nixos.org/nixos-24.05/latest-nixos-minimal-x86_64-linux.iso"
  fi

  # ── v2: Also prepare hermes-boot.img if it exists ─────────────────────
  local boot_img="$(dirname "$0")/../boot-image/hermes-boot.img"
  if [[ -f "$boot_img" ]]; then
    log "hermes-boot.img found — it will be written to a separate USB or first partition"
    echo "  To create a dual-partition USB:"
    echo "    1. Write boot image: sudo dd if=$boot_img of=${usb_dev} bs=4M"
    echo "    2. Create second partition for data"
    echo "  Or use a SEPARATE USB for the boot image."
  else
    warn "hermes-boot.img not found at $boot_img"
    echo "  Build it first: cd boot-image/ && sudo ./make-boot-image.sh"
  fi

  sync
  umount "$mp"

  log "${GREEN}USB stick ready!${RESET}"
  log ""
  log "USB contents:"
  lsblk -o NAME,SIZE,FSTYPE,LABEL "$usb_dev"
  echo ""
  log "Next: Boot target machine from USB, then run --partition + --bootstrap"
  echo ""
  log "NOTE: If using hermes-boot.img approach:"
  log "  1. Write boot image to USB: sudo dd if=boot-image/hermes-boot.img of=/dev/sdX bs=4M"
  log "  2. Boot target from USB — auto-deploy.sh runs automatically"
  echo ""
}

# ═══════════════════════════════════════════════════════════════════════════
# STEP 2: Partition internal SSD
# ═══════════════════════════════════════════════════════════════════════════
partition_internal() {
  local ssd_dev="$1"

  check_root

  log "${BOLD}Partitioning internal SSD${RESET}"
  hardware_detect "Internal SSD — Pre-Partition"
  echo ""
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
  done < <(list_partition_paths "$ssd_dev")

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

  local efi_part root_part
  efi_part=$(partition_path "$ssd_dev" 1)
  root_part=$(partition_path "$ssd_dev" 2)

  # Format
  log "Formatting EFI..."
  mkfs.fat -F 32 -n EFI "$efi_part" >/dev/null

  log "Formatting root..."
  mkfs.ext4 -L HERMES -E lazy_itable_init "$root_part"

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
  hardware_detect "NixOS Bootstrap — Pre-Install"

  # ── v2: Network bring-up before anything else ──────────────────────────
  echo ""
  log "${BOLD}=== Network Setup ===${RESET}"
  if wifi_setup; then
    log "Network ready — proceeding with installation."
  else
    warn "Network unavailable — installation may fail if NixOS needs to download packages."
    if [[ -t 0 ]]; then
      printf 'Continue anyway? [y/N]: '
      read -r answer
      case "${answer}" in y|yes|Y|YES) ;; *)
        echo "Aborted."
        exit 1
      esac
    fi
  fi

  # Detect partitions
  local efi_dev
  local root_dev
  efi_dev=$(partition_path "$ssd_dev" 1)
  root_dev=$(partition_path "$ssd_dev" 2)

  log "Mounting root: $root_dev → /mnt"
  mount "$root_dev" /mnt

  log "Mounting EFI: $efi_dev → /mnt/boot/efi"
  mkdir -p /mnt/boot/efi
  mount "$efi_dev" /mnt/boot/efi

  # ── v2: Find hermes-bootstrap on any USB partition (with retry) ─────────
  log "Looking for hermes-bootstrap on mounted devices..."
  local found_src=""
  for mp in /mnt/boot /mnt/boot/ventoy /mnt; do
    if [[ -d "$mp/hermes-bootstrap" ]]; then
      found_src="$mp/hermes-bootstrap"
      log "Found at: $found_src"
      break
    fi
  done

  if [[ -z "$found_src" ]]; then
    # Try to mount USB
    warn "hermes-bootstrap not found. Looking for USB..."
    for dev in /dev/sd*1 /dev/nvme*p1 /dev/sd*2 /dev/nvme*p2; do
      [[ -b "$dev" ]] || continue
      mkdir -p /mnt/usb-bootstrap
      if usb_mount_retry "$dev" /mnt/usb-bootstrap; then
        if [[ -d /mnt/usb-bootstrap/hermes-bootstrap ]]; then
          found_src="/mnt/usb-bootstrap/hermes-bootstrap"
          log "Found on USB at $dev"
          break
        fi
        umount /mnt/usb-bootstrap 2>/dev/null || true
      fi
    done
  fi

  bootstrap_src="${found_src:-${bootstrap_src}}"

  # Copy bootstrap
  log "Copying hermes-bootstrap to /mnt..."
  if [[ -d "$bootstrap_src" ]]; then
    cp -r "$bootstrap_src" /mnt/hermes-bootstrap 2>/dev/null || error "Failed to copy bootstrap"
  else
    error "hermes-bootstrap source not found at $bootstrap_src"
  fi

  # Generate target-specific hardware config. Prefer nixos-generate-config output:
  # it captures real filesystems, disk UUIDs, CPU/GPU modules, firmware needs, and
  # avoids carrying CI/template assumptions such as qemu-guest into bare metal.
  log "Generating hardware config..."
  nixos-generate-config --root /mnt --force

  if [[ ! -s /mnt/etc/nixos/hardware-configuration.nix ]]; then
    warn "nixos-generate-config did not produce hardware-configuration.nix; writing minimal fallback"
    cat > /mnt/etc/nixos/hardware-configuration.nix << HWEOF
# Minimal fallback hardware config — generated by hermes-bootstrap.
# Prefer nixos-generate-config output when available.
{ config, lib, pkgs, modulesPath, ... }:

{
  boot.initrd.availableKernelModules = [
    "ahci" "xhci_pci" "usb_storage" "nvme" "ext4" "vfat" "sr_mod" "sd_mod"
  ];

  fileSystems = {
    "/" = { device = "${root_dev}"; fsType = "ext4"; options = ["defaults" "noatime"]; };
    "/boot/efi" = { device = "${efi_dev}"; fsType = "vfat"; options = ["defaults"]; };
  };

  networking.useDHCP = lib.mkDefault true;
}
HWEOF
  fi

  # Install the flake into the target system. Do not use
  # `nixos-install --flake` here: it has proven unreliable from live USB
  # environments. Build from inside the target root with nixos-enter instead.
  log "Installing flake files into /mnt/etc/nixos..."
  mkdir -p /mnt/etc/nixos
  cp /mnt/hermes-bootstrap/system/nixos/flake.nix /mnt/etc/nixos/flake.nix
  cp /mnt/hermes-bootstrap/system/nixos/deployment-options.nix /mnt/etc/nixos/deployment-options.nix
  cp /mnt/hermes-bootstrap/system/nixos/agent-extra-packages.nix /mnt/etc/nixos/agent-extra-packages.nix
  if [[ -f /mnt/hermes-bootstrap/system/nixos/flake.lock ]]; then
    cp /mnt/hermes-bootstrap/system/nixos/flake.lock /mnt/etc/nixos/flake.lock
  fi

  cat > /mnt/etc/nixos/configuration.nix << 'CFGEOF'
# Hermes Bootstrap uses the flake in this directory:
#   nixos-rebuild switch --flake /etc/nixos#hermes
# This file is kept as a pointer for operators and non-flake tools.
{ ... }: { }
CFGEOF

  # ── Pre-rebuild: seed secrets because hermes-agent reads environmentFiles ──
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
# MINIMAX_API_KEY=replace-with-real-key
SECRETS_EOF
    chmod 0640 /mnt/var/lib/hermes/secrets/hermes.env
    warn "No hermes.env found on USB — created placeholder at /var/lib/hermes/secrets/hermes.env"
  fi

  # Wire secrets into the flake's environmentFiles
  # (The flake references /var/lib/hermes/secrets/hermes.env via environmentFiles)

  # Run the reliable flake install path from inside the target root.
  log "Installing NixOS via nixos-enter + nixos-rebuild (this takes 10-30 minutes)..."
  nixos-enter --root /mnt -- /bin/sh -c '
    cd /etc/nixos &&
    nixos-rebuild switch \
      --flake .#hermes \
      --option sandbox false \
      --option accept-flake-config true
  '

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
${BOLD}Hermes OS Deploy Script (v2)${RESET}

${BOLD}USAGE:${RESET}
  $0 --prepare-usb /dev/sdX        Prepare bootable USB (FAT32, copy files)
  $0 --partition /dev/nvme0n1      Partition internal SSD (interactive)
  $0 --bootstrap /dev/nvme0n1      Bootstrap NixOS (run from NixOS installer)
  $0 --all /dev/sdX /dev/nvme0n1  Full pipeline (prepare + partition + install)

${BOLD}V2 FLOW:${RESET}
  1. Build boot image:  cd boot-image/ && sudo ./make-boot-image.sh
  2. Write to USB:       sudo dd if=boot-image/hermes-boot.img of=/dev/sdX bs=4M
  3. Copy data:          (boot-image copies hermes-bootstrap + ISO to USB)
  4. Boot target from USB → auto-deploy.sh runs automatically

  OR (simpler, manual):
  1. Run --prepare-usb to copy files to FAT32 USB
  2. Boot target from USB into NixOS installer
  3. Run --partition --bootstrap manually in the installer

${BOLD}EXAMPLES:${RESET}
  # Full v2 USB preparation
  git clone https://github.com/steezkelly/hermes-bootstrap.git
  cd hermes-bootstrap
  ./scripts/setup-hermes-agent.sh --copy ~/.hermes/hermes-agent
  wget https://channels.nixos.org/nixos-24.05/latest-nixos-minimal-x86_64-linux.iso
  sudo ./scripts/deploy-hermes.sh --prepare-usb /dev/sdb

  # On target machine (NixOS installer TTY):
  sudo ./hermes-bootstrap/scripts/deploy-hermes.sh --partition /dev/nvme0n1
  sudo ./hermes-bootstrap/scripts/deploy-hermes.sh --bootstrap /dev/nvme0n1

${BOLD}V1 → V2 CHANGES:${RESET}
  - Removed Ventoy dependency (Ventoy timeout was causing gray screens)
  - Removed SquashFS (source of I/O errors on target hardware)
  - Added WiFi auto-config with guided fallback
  - Added USB I/O retry logic
  - Added hardware detection output at every step
  - hermes-agent-src must be pre-bundled (no git clone during install)

${BOLD}VENTOY FALLBACK (if hermes-boot.img doesn't boot):${RESET}
  If direct ISO boot fails on target hardware, fall back to Ventoy:
    1. Download Ventoy: https://github.com/Ventoy/Ventoy/releases
    2. Install: sudo ./Ventoy2Disk.sh -i /dev/sdX
    3. Copy NixOS ISO to Ventoy partition
    4. Boot → Ventoy menu → select ISO

${BOLD}POST-INSTALL:${RESET}
  After reboot:
    ssh hermes-admin@hermes-node.local
    systemctl status hermes-agent
    hermes status
    # Add API key:
    sudo nano /var/lib/hermes/secrets/hermes.env
    sudo systemctl restart hermes-agent

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
      bootstrap_nixos "$arg1" "${arg2:-}" ;;
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
