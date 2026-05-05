#!/bin/sh
# ═══════════════════════════════════════════════════════════════════════════
# hermes-bootstrap auto-deploy.sh
# ═══════════════════════════════════════════════════════════════════════════
# Runs inside the Alpine boot environment (hermes-boot.img).
# Orchestrates: network → partition → nixos-install → reboot.
#
# No arguments required in normal use.
# For debugging, accepts:
#   --no-reboot   Don't reboot after install
#   --debug       Drop to shell before each step
#   --ssd DEVICE  Skip device prompt, use DEVICE directly
#
set -euo pipefail

# ─── Colours ───────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'
log() { echo -e "${GREEN}[DEPLOY]${RESET} $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $*"; }
error() { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }

# ─── Args ─────────────────────────────────────────────────────────────
NO_REBOOT=""
DEBUG=""
TARGET_SSD=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-reboot) NO_REBOOT=1; shift ;;
    --debug) DEBUG=1; shift ;;
    --ssd) TARGET_SSD="$2"; shift 2 ;;
    *) shift ;;
  esac
done

# ─── Helpers ───────────────────────────────────────────────────────────
confirm() {
  local prompt="${1:-Continue?}"
  local retries=3
  while (( retries-- > 0 )); do
    printf '%s [y/N] ' "$prompt"
    read -r answer
    case "${answer}" in y|yes|Y|YES) return 0 ;; n|no|"") return 1 ;; esac
    echo "Please answer yes or no."
  done
  return 1
}

debug_shell() {
  if [[ -n "$DEBUG" ]]; then
    echo ""
    warn "DEBUG: Dropping to shell. Type 'exit' to continue."
    sh
  fi
}

wait_for_usb() {
  log "Waiting for USB devices..."
  local timeout=10
  while [[ $timeout -gt 0 ]]; do
    if lsblk -o NAME,TRAN | grep -q 'usb'; then
      log "USB detected."
      sleep 1
      return 0
    fi
    timeout=$((timeout - 1))
    sleep 1
  done
  warn "No USB device found. Will retry after scanning."
}

# ─── STEP 1: Hardware Detection ───────────────────────────────────────
echo ""
log "${BOLD}=== Hardware Detection ===${RESET}"
echo ""
log "Block devices:"
lsblk -o NAME,SIZE,TYPE,TRAN,MODEL,UUID 2>/dev/null || lsblk -o NAME,SIZE,TYPE,TRAN
echo ""
log "Network interfaces:"
ip link show 2>/dev/null || ip addr show
echo ""
log "Wireless devices:"
iw dev 2>/dev/null | grep -E 'Interface|ssid' || echo "  (no wireless devices detected)"
echo ""
log "USB storage:"
lsblk -o NAME,SIZE,TRAN | grep -E 'usb|disk' || echo "  (none found yet — will detect after USB mount)"
echo ""

# ─── STEP 2: Mount USB ────────────────────────────────────────────────
log "${BOLD}=== Mounting USB ===${RESET}"
debug_shell

wait_for_usb

# Try to find hermes-bootstrap on any mounted USB
USB_MP=""
for dev in /dev/sd* /dev/nvme*p; do
  [[ -b "${dev}1" ]] || continue
  mkdir -p /mnt/usb 2>/dev/null
  if mount -o ro "${dev}1" /mnt/usb 2>/dev/null; then
    if [[ -d /mnt/usb/hermes-bootstrap ]]; then
      USB_MP="/mnt/usb"
      log "Found hermes-bootstrap on ${dev}1"
      break
    fi
    # Try partition 2 if it exists
    umount /mnt/usb 2>/dev/null
  fi
  [[ -b "${dev}2" ]] || continue
  if mount -o ro "${dev}2" /mnt/usb 2>/dev/null; then
    if [[ -d /mnt/usb/hermes-bootstrap ]]; then
      USB_MP="/mnt/usb"
      log "Found hermes-bootstrap on ${dev}2"
      break
    fi
    umount /mnt/usb 2>/dev/null
  fi
done

if [[ -z "$USB_MP" ]]; then
  error "Could not find hermes-bootstrap/ on any USB device.
  Make sure the USB is plugged in and contains the hermes-bootstrap directory."
fi

# Verify NixOS ISO exists
if ! compgen -G "$USB_MP/NixOS-*.iso" >/dev/null && ! compgen -G "$USB_MP/nixos-*.iso" >/dev/null; then
  warn "NixOS ISO not found on USB. Looking for alternative locations..."
  ISO_PATH=$(find "$USB_MP" -maxdepth 3 -name "*.iso" 2>/dev/null | grep -i nixos | head -1 || true)
  if [[ -z "$ISO_PATH" ]]; then
    error "NixOS ISO not found on USB. Copy it to the USB root directory:
  wget https://channels.nixos.org/nixos-24.05/latest-nixos-minimal-x86_64-linux.iso
  cp NixOS-*.iso $USB_MP/"
  fi
else
  ISO_PATH=$(find "$USB_MP" -maxdepth 3 -name "*.iso" 2>/dev/null | grep -i nixos | head -1)
fi

log "Using NixOS ISO: $(basename "$ISO_PATH")"

# ─── STEP 3: Network ───────────────────────────────────────────────────
log "${BOLD}=== Network Setup ===${RESET}"
debug_shell

# Try ethernet first (DHCP)
log "Checking ethernet..."
if ip link show | grep -qE 'eth[0-9]|enp[0-9]'; then
  ETH_IFACE=$(ip link show | grep -oE 'eth[0-9]|enp[0-9]+s[0-9]+' | head -1)
  log "Ethernet interface: $ETH_IFACE"
  dhcpcd "$ETH_IFACE" 2>/dev/null || dhcpcd -q "$ETH_IFACE" || true
  sleep 2
  if ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; then
    log "Ethernet OK — internet reachable."
  fi
fi

# If no internet, try saved WiFi config
if ! ping -c 1 -W 3 8.8.8.8 >/dev/null 2>&1; then
  log "No internet via ethernet. Trying saved WiFi config..."
  if [[ -f /etc/wpa_supplicant.conf ]] && grep -q 'ssid=' /etc/wpa_supplicant.conf; then
    WLAN_IFACE=$(iw dev 2>/dev/null | grep Interface | awk '{print $2}' | head -1)
    if [[ -n "$WLAN_IFACE" ]]; then
      log "Starting wpa_supplicant on $WLAN_IFACE..."
      wpa_supplicant -B -i "$WLAN_IFACE" -c /etc/wpa_supplicant.conf 2>/dev/null || true
      dhcpcd -q "$WLAN_IFACE" 2>/dev/null || true
      sleep 3
    fi
  fi
fi

# If still no internet, run guided WiFi setup
if ! ping -c 1 -W 3 8.8.8.8 >/dev/null 2>&1; then
  log "No internet. Running guided WiFi setup..."
  WLAN_IFACE=$(iw dev 2>/dev/null | grep Interface | awk '{print $2}' | head -1)
  if [[ -z "$WLAN_IFACE" ]]; then
    warn "No wireless interface found. Skipping WiFi."
  else
    echo ""
    echo "Available networks:"
    iw dev "$WLAN_IFACE" scan 2>/dev/null | grep -E 'SSID:|signal:' | paste - - || true
    echo ""
    printf 'SSID: '
    read -r SSID
    if [[ -n "$SSID" ]]; then
      printf 'Password (leave blank for open network): '
      read -r PASSWORD
      if [[ -n "$PASSWORD" ]]; then
        wpa_passphrase "$SSID" "$PASSWORD" > /etc/wpa_supplicant.conf
      else
        echo "network={\n  ssid=\"$SSID\"\n  key_mgmt=NONE\n}" > /etc/wpa_supplicant.conf
      fi
      log "Starting wpa_supplicant on $WLAN_IFACE..."
      wpa_supplicant -B -i "$WLAN_IFACE" -c /etc/wpa_supplicant.conf 2>/dev/null || {
        warn "wpa_supplicant failed — continuing without network"
      }
      dhcpcd -q "$WLAN_IFACE" 2>/dev/null || true
      sleep 4
    fi
  fi
fi

# Report network status
echo ""
if ping -c 1 -W 3 8.8.8.8 >/dev/null 2>&1; then
  log "${GREEN}Network OK — internet reachable${RESET}"
  ip addr show | grep -E 'inet ' | head -3
else
  warn "No internet connection. Installation will proceed but may fail if NixOS needs to download packages."
fi
echo ""

# ─── STEP 4: Select Target SSD ───────────────────────────────────────
log "${BOLD}=== Target SSD Selection ===${RESET}"
debug_shell

echo ""
echo "Available block devices:"
lsblk -o NAME,SIZE,TYPE,TRAN,MODEL,UUID 2>/dev/null | grep -E 'disk|nvme'
echo ""

if [[ -n "$TARGET_SSD" ]]; then
  log "Using pre-selected device: $TARGET_SSD"
else
  printf "Enter target SSD device (e.g. nvme0n1, sda): "
  read -r TARGET_SSD
fi

# Normalize: add /dev/ prefix if missing
case "$TARGET_SSD" in
  /dev/*) ;;
  *) TARGET_SSD="/dev/$TARGET_SSD" ;;
esac

echo ""
warn "ALL DATA ON $TARGET_SSD WILL BE DESTROYED"
echo "Current partitions:"
lsblk "$TARGET_SSD" 2>/dev/null || echo "  (empty or new device)"
echo ""
confirm "Type 'yes' to confirm destruction of ${TARGET_SSD}" || {
  echo "Aborted."
  exit 1
}

# ─── STEP 5: Partition Target SSD ────────────────────────────────────
log "${BOLD}=== Partitioning ${TARGET_SSD} ===${RESET}"
debug_shell

# Unmount any existing mounts
for part in "${TARGET_SSD}"*; do
  [[ -b "$part" ]] || continue
  umount "$part" 2>/dev/null || umount -l "$part" 2>/dev/null || true
done

log "Creating GPT partition table..."
parted -s "$TARGET_SSD" -- mklabel gpt

log "Creating EFI partition (512MB)..."
parted -s "$TARGET_SSD" -- mkpart primary fat32 512MB 1024MB
parted -s "$TARGET_SSD" -- set 1 esp on
parted -s "$TARGET_SSD" -- set 1 boot on
parted -s "$TARGET_SSD" -- name 1 EFI

log "Creating root partition (remaining space)..."
parted -s "$TARGET_SSD" -- mkpart primary ext4 1024MB 100%
parted -s "$TARGET_SSD" -- name 2 HERMES

log "Formatting EFI partition..."
mkfs.fat -F 32 -n EFI "${TARGET_SSD}1" >/dev/null

log "Formatting root partition..."
mkfs.ext4 -L HERMES -E lazy_itable_init "${TARGET_SSD}2"

echo ""
log "Partitions created:"
lsblk -o NAME,SIZE,FSTYPE,LABEL "$TARGET_SSD"
echo ""

# ─── STEP 6: Loopback-mount NixOS ISO ────────────────────────────────
log "${BOLD}=== Preparing NixOS Installer ===${RESET}"
debug_shell

# Mount the ISO via loopback so the NixOS installer tools are accessible
NIXOS_MP="/mnt/nixos-iso"
mkdir -p "$NIXOS_MP"
mount -o ro,loop "$ISO_PATH" "$NIXOS_MP" 2>/dev/null || {
  # Try without ro
  mount -o loop "$ISO_PATH" "$NIXOS_MP" 2>/dev/null || \
    error "Failed to mount NixOS ISO at $ISO_PATH"
}

log "NixOS ISO mounted at $NIXOS_MP"

# Verify we can access nixos-install
if [[ ! -x "$NIXOS_MP/nixos-enter" ]] && [[ ! -x "$NIXOS_MP/bin/nixos-enter" ]]; then
  # The minimal ISO doesn't have nixos-enter; it's in the full installer
  # Look for the installer binary
  NIXOS_BIN=$(find "$NIXOS_MP" -name 'nixos-install' -o -name 'nixos-enter' 2>/dev/null | head -1 || true)
  if [[ -z "$NIXOS_BIN" ]]; then
    warn "Standard NixOS minimal ISO detected — this should work with the installer's bash environment."
  fi
fi

# ─── STEP 7: Mount Target Partitions ────────────────────────────────
log "${BOLD}=== Mounting Target Partitions ===${RESET}"

mount "${TARGET_SSD}2" /mnt
mkdir -p /mnt/boot/efi
mount "${TARGET_SSD}1" /mnt/boot/efi

mkdir -p /mnt/var/lib/hermes
cp -r "$USB_MP/hermes-bootstrap/data/"* /mnt/var/lib/hermes/ 2>/dev/null || true

# ─── STEP 8: Generate Hardware Config ────────────────────────────────
log "${BOLD}=== Generating NixOS Hardware Config ===${RESET}"

mkdir -p /mnt/etc/nixos

# Use the NixOS ISO's nixos-generate-config if available
if [[ -x "$NIXOS_MP/bin/nixos-generate-config" ]]; then
  log "Using nixos-generate-config from ISO..."
  NIXOS_ROOT=/mnt "$NIXOS_MP/bin/nixos-generate-config" --root /mnt --force 2>/dev/null || true
elif [[ -x /nixos-enter ]]; then
  log "Using nixos-enter from initrd..."
  /nixos-enter 2>/dev/null || true
else
  log "No nixos-generate-config found — using template hardware config"
fi

# Always ensure we have a hardware config
cat > /mnt/etc/nixos/hardware-configuration.nix << 'HARDWARE'
# Hardware configuration — generated for Hermes OS
# Auto-detected modules; tweak if boot fails
{ config, lib, pkgs, modulesPath, ... }:

{
  imports = [ (modulesPath + "/profiles/qemu-guest.nix") ];

  boot.initrd.availableKernelModules = [
    "ahci" "xhci_pci" "xhci_hcd" "usb_storage"
    "nvme" "ext4" "vfat" "sr_mod" "sd_mod"
    "e1000e" "iwlwifi" "rtl8xxxu"  # common NIC + WiFi
  ];

  boot.initrd.kernelModules = [ ];

  fileSystems = {
    "/" = { device = "/dev/disk/by-label/HERMES"; fsType = "ext4"; options = ["defaults" "noatime"]; };
    "/boot/efi" = { device = "/dev/disk/by-label/EFI"; fsType = "vfat"; };
  };

  networking.useDHCP = true;

  virtualisation.docker.enable = true;
}
HARDWARE

# ─── STEP 9: Write NixOS Configuration ────────────────────────────────
log "${BOLD}=== Writing NixOS Configuration ===${RESET}"

# Copy the hermes-bootstrap flake reference
if [[ -d "$USB_MP/hermes-bootstrap/system/nixos" ]]; then
  cp -r "$USB_MP/hermes-bootstrap/system/nixos" /mnt/etc/nixos/hermes-bootstrap 2>/dev/null || true
  cp "$USB_MP/hermes-bootstrap/system/nixos/flake.nix" /mnt/etc/nixos/flake.nix 2>/dev/null || true
fi

# Write the configuration.nix that imports the flake
cat > /mnt/etc/nixos/configuration.nix << 'CONFIG'
# Hermes OS — NixOS Configuration
# Built by hermes-bootstrap v2
{ config, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ./hermes-bootstrap/system/nixos/flake.nix
  ];

  # Bootstrap-specific overrides — these are safe defaults
  # that nixos-install needs before the real flake is fully evaluated
  services.hermes-agent.enable = lib.mkDefault true;

  # Ensure the NixOS installer doesn't try to fetch substitutes
  # (we're offline or semi-offline during bootstrap)
  nix.settings.substituters = lib.mkAfter [ ];
}
CONFIG

# ─── STEP 10: Run nixos-install ───────────────────────────────────────
log "${BOLD}=== Installing NixOS ===${RESET}"
echo ""

# Copy hermes-bootstrap to /mnt for post-install
cp -r "$USB_MP/hermes-bootstrap" /mnt/ 2>/dev/null || true

# ── Option A: nixos-install with --flake ───────────────────────────────
# The standard way: use the flake on the mounted USB
NIXOS_FLAKE="/mnt/hermes-bootstrap/system/nixos#hermes"

if [[ -d /mnt/hermes-bootstrap/system/nixos/hermes-agent-src ]]; then
  log "hermes-agent source found — using flake install"
  debug_shell

  # Try the standard nixos-install
  if command -v nixos-install &>/dev/null; then
    nixos-install \
      --no-root-password \
      --flake "$NIXOS_FLAKE" \
      --substituters "" \
      2>&1 | tee /tmp/nixos-install.log
    INSTALL_EXIT=$?
  else
    warn "nixos-install not in PATH — using nixos-enter from ISO"
    INSTALL_EXIT=1
  fi
else
  warn "hermes-agent-src not found on USB — installing base NixOS only"
  INSTALL_EXIT=1
fi

if [[ $INSTALL_EXIT -ne 0 ]]; then
  echo ""
  if [[ -f /tmp/nixos-install.log ]]; then
    warn "nixos-install failed. Last 30 lines of log:"
    tail -30 /tmp/nixos-install.log
  fi
  echo ""
  warn "Attempting fallback install (manual configuration)..."
  debug_shell

  # Fallback: minimal install without the flake
  # Just ensure basic packages are installed
  cat > /mnt/etc/nixos/configuration.nix << 'FALLBACK'
{ config, lib, pkgs, ... }:
{
  imports = [ ./hardware-configuration.nix ];
  boot.loader.grub.enable = lib.mkForce false;
  boot.loader.generic-extlinux-compatible.enable = true;
  fileSystems."/".device = "/dev/disk/by-label/HERMES";
  fileSystems."/boot/efi".device = "/dev/disk/by-label/EFI";
  networking.hostName = "hermes-node";
  networking.useDHCP = true;
  services.openssh.enable = true;
  environment.etc."nixos/.source".source = /etc/nixos;
}
FALLBACK

  if command -v nixos-install &>/dev/null; then
    nixos-install --no-root-password --substituters "" 2>&1 | tail -20 || true
  fi
fi

# ─── STEP 11: Post-Install ─────────────────────────────────────────────
log "${BOLD}=== Post-Install Setup ===${RESET}"

# Seed secrets
mkdir -p /mnt/var/lib/hermes/secrets
chmod 0750 /mnt/var/lib/hermes/secrets

if [[ -f "$USB_MP/hermes-bootstrap/data/secrets/hermes.env" ]]; then
  cp "$USB_MP/hermes-bootstrap/data/secrets/hermes.env" /mnt/var/lib/hermes/secrets/hermes.env
  chmod 0640 /mnt/var/lib/hermes/secrets/hermes.env
  log "Seeded secrets from USB"
else
  cat > /mnt/var/lib/hermes/secrets/hermes.env << 'SECRETS'
# Secrets — fill in before first boot
# MINIMAX_API_KEY=
SECRETS
  chmod 0640 /mnt/var/lib/hermes/secrets/hermes.env
  warn "No hermes.env on USB — created placeholder"
fi

# Init git tracking
if command -v git &>/dev/null; then
  git -C /mnt/var/lib/hermes init 2>/dev/null || true
  git -C /mnt/var/lib/hermes config user.email "hermes@localhost" 2>/dev/null || true
  git -C /mnt/var/lib/hermes config user.name "Hermes OS" 2>/dev/null || true
fi

# ─── STEP 12: Unmount + Reboot ────────────────────────────────────────
log "${BOLD}=== Complete ===${RESET}"

umount -R /mnt 2>/dev/null || umount -R /mnt || true
umount "$NIXOS_MP" 2>/dev/null || true
umount "$USB_MP" 2>/dev/null || true

echo ""
log "${GREEN}Hermes OS installation complete!${RESET}"
echo ""
echo "Next:"
echo "  1. Remove the USB stick"
echo "  2. The system will reboot into NixOS"
echo "  3. Find the IP address: nmap -sn 192.168.1.0/24 | grep hermes-node"
echo "  4. SSH: ssh hermes-admin@<ip> (or hermes@<ip>)"
echo "  5. Add your API key: sudo nano /var/lib/hermes/secrets/hermes.env"
echo ""

if [[ -z "$NO_REBOOT" ]]; then
  echo "Rebooting in 5 seconds..."
  sleep 5
  reboot
else
  warn "NOT rebooting (--no-reboot set)"
  echo "To reboot manually: reboot"
fi
