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
  if [[ "${HERMES_AUTO_CONFIRM:-0}" == "1" ]]; then
    warn "$prompt [auto-confirmed by HERMES_AUTO_CONFIRM=1]"
    return 0
  fi

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

# ─── Network / WiFi Setup ────────────────────────────────────────────────
# Bring up network with NixOS-live-friendly diagnostics. wpa_supplicant
# "successfully initialized" only means the daemon started; this verifies
# association, DHCP/default route, DNS, and HTTPS reachability.
net_ok() {
  curl -fsSIL --connect-timeout 5 --max-time 12 https://github.com >/dev/null 2>&1 \
    || ping -c 1 -W 3 1.1.1.1 >/dev/null 2>&1
}

run_dhcp() {
  local iface="$1"
  if command -v dhcpcd >/dev/null 2>&1; then
    dhcpcd -4 -q "$iface" 2>/dev/null || dhcpcd -q "$iface" 2>/dev/null || true
  fi

  if ! ip route | grep -q '^default '; then
    if command -v systemctl >/dev/null 2>&1; then
      mkdir -p /etc/systemd/network
      cat > "/etc/systemd/network/25-${iface}.network" << NETEOF
[Match]
Name=${iface}

[Network]
DHCP=yes
DNS=1.1.1.1
DNS=8.8.8.8
NETEOF
      systemctl restart systemd-networkd 2>/dev/null || true
    fi
  fi

  sleep 5
  if ! grep -q '^nameserver' /etc/resolv.conf 2>/dev/null; then
    printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\n' > /etc/resolv.conf 2>/dev/null || true
  fi
}

wifi_setup() {
  local max_wait="${1:-8}"

  if net_ok; then
    log "Network already OK — GitHub reachable."
    return 0
  fi

  # Try any non-loopback wired/up interface first. QEMU/NixOS commonly uses
  # enp0s4; physical machines vary (enp*, eno*, eth*).
  local eth_iface
  eth_iface=$(ip -br link show 2>/dev/null | awk '$1 != "lo" {print $1; exit}' || true)
  if [[ -n "$eth_iface" ]]; then
    log "Trying network interface ($eth_iface)..."
    ip link set "$eth_iface" up 2>/dev/null || true
    run_dhcp "$eth_iface"
    if net_ok; then
      log "Network OK on $eth_iface — GitHub reachable."
      return 0
    fi
  fi

  local wlan_iface
  wlan_iface=$(iw dev 2>/dev/null | awk '/Interface/ {print $2; exit}' || true)
  if [[ -z "$wlan_iface" ]]; then
    warn "No wireless interface found and internet is not reachable."
    ip -br addr show 2>/dev/null || true
    ip route 2>/dev/null || true
    return 1
  fi

  log "Wireless interface: $wlan_iface"
  ip link set "$wlan_iface" up 2>/dev/null || true

  echo ""
  warn "WiFi setup required."
  echo "Available networks on $wlan_iface:"
  iw dev "$wlan_iface" scan 2>/dev/null | grep -E 'SSID:|signal:' | paste - - 2>/dev/null || echo "  (scan failed)"
  echo ""

  local ssid=""
  local password=""
  printf 'SSID: '
  read -r ssid
  [[ -n "$ssid" ]] || { warn "No SSID entered. Skipping WiFi."; return 1; }

  printf 'Password (leave blank for open network): '
  read -r password
  if [[ -n "$password" ]]; then
    wpa_passphrase "$ssid" "$password" > /etc/wpa_supplicant.conf
  else
    printf 'network={\n  ssid="%s"\n  key_mgmt=NONE\n}\n' "$ssid" > /etc/wpa_supplicant.conf
  fi
  chmod 600 /etc/wpa_supplicant.conf

  log "Starting wpa_supplicant on $wlan_iface..."
  pkill wpa_supplicant 2>/dev/null || true
  rm -rf /run/wpa_supplicant
  mkdir -p /run/wpa_supplicant
  wpa_supplicant -B -i "$wlan_iface" -c /etc/wpa_supplicant.conf -C /run/wpa_supplicant 2>/dev/null || {
    warn "wpa_supplicant failed. Check dmesg for driver issues."
    return 1
  }

  local state=""
  for _ in $(seq 1 "$max_wait"); do
    state=$(wpa_cli -p /run/wpa_supplicant -i "$wlan_iface" status 2>/dev/null | awk -F= '/^wpa_state=/ {print $2}' || true)
    [[ "$state" == "COMPLETED" ]] && break
    sleep 1
  done
  if [[ "$state" != "COMPLETED" ]]; then
    warn "WiFi did not associate; wpa_state=${state:-unknown}"
    wpa_cli -p /run/wpa_supplicant -i "$wlan_iface" status 2>/dev/null || true
    return 1
  fi
  log "WiFi associated with router. Requesting DHCP..."

  run_dhcp "$wlan_iface"

  echo "Network diagnostics:"
  ip -br addr show "$wlan_iface" 2>/dev/null || true
  ip route 2>/dev/null || true
  cat /etc/resolv.conf 2>/dev/null || true

  if net_ok; then
    log "WiFi OK — GitHub reachable."
    return 0
  fi

  warn "WiFi associated, but internet/DNS check still failed."
  return 1
}

nix_option_string() {
  local file="$1"
  local key="$2"
  sed -nE "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*\"([^\"]*)\";[[:space:]]*$/\1/p" "$file" | head -1
}

nix_option_bool_true() {
  local file="$1"
  local key="$2"
  grep -Eq "^[[:space:]]*${key}[[:space:]]*=[[:space:]]*true;" "$file"
}

stage_patched_hermes_agent_source() {
  local target_nixos_dir="$1"
  local rev="d12f59aa5377635f7f4ad680cc349bf3e770a5d8"
  local old_hash="sha256-a/HGI9OgVcTnZrMXA7xFMGnFoVxyHe95fulVz+WNYB0="
  local new_hash="sha256-MLcLhjTF6dgdvNBtJWzo8Nh19eNh/ZitD2b07nm61Tc="
  local src_dir="$target_nixos_dir/hermes-agent-src"

  if [[ -f "$src_dir/flake.nix" ]]; then
    log "Using existing hermes-agent source at $src_dir"
  else
    log "Staging hermes-agent source at locked rev $rev..."
    rm -rf "$src_dir"
    mkdir -p "$src_dir"
    curl -fsSL "https://github.com/NousResearch/hermes-agent/archive/${rev}.tar.gz" \
      | tar -xz --strip-components=1 -C "$src_dir"
  fi

  if [[ -f "$src_dir/nix/tui.nix" ]] && grep -q "$old_hash" "$src_dir/nix/tui.nix"; then
    warn "Patching hermes-agent TUI npmDeps hash for live install reproducibility."
    sed -i "s#${old_hash}#${new_hash}#" "$src_dir/nix/tui.nix"
  fi

  if grep -q 'hermes-agent.url = "github:NousResearch/hermes-agent";' "$target_nixos_dir/flake.nix"; then
    sed -i 's#hermes-agent.url = "github:NousResearch/hermes-agent";#hermes-agent.url = "path:./hermes-agent-src";#' "$target_nixos_dir/flake.nix"
  fi

  # The committed lock points at the upstream GitHub input. The target flake now
  # uses a local patched path input, so let nix create a matching lock file.
  rm -f "$target_nixos_dir/flake.lock"
}

container_mode_preflight() {
  local options_file="$1"
  local target_root="$2"
  local bootstrap_src="$3"

  [[ -f "$options_file" ]] || error "deployment options not found: $options_file"

  if ! nix_option_bool_true "$options_file" "containerMode"; then
    log "Container mode disabled — native first boot remains network-independent from Docker/apt/uv provisioning."
    return 0
  fi

  local backend image archive_src archive_dst archive_count=0
  backend=$(nix_option_string "$options_file" "containerBackend")
  image=$(nix_option_string "$options_file" "containerImage")
  backend="${backend:-docker}"
  image="${image:-ubuntu:24.04}"
  archive_src="$bootstrap_src/data/container-images"
  archive_dst=$(nix_option_string "$options_file" "containerImageArchiveDir")
  archive_dst="${archive_dst:-/var/lib/hermes/container-images}"
  archive_dst="$target_root/${archive_dst#/}"

  warn "containerMode = true — first hermes-agent start will use upstream OCI container mode."
  warn "Configured container backend/image: ${backend} / ${image}"
  warn "Cold start can require: registry pull, Ubuntu apt, NodeSource, Astral uv, and uv Python downloads."

  mkdir -p "$archive_dst"
  if [[ -d "$archive_src" ]]; then
    while IFS= read -r archive; do
      cp "$archive" "$archive_dst/"
      archive_count=$((archive_count + 1))
    done < <(find "$archive_src" -maxdepth 1 -type f \( -name '*.tar' -o -name '*.tar.gz' -o -name '*.oci' \) | sort)
  fi

  if (( archive_count > 0 )); then
    local display_archive_dst="/${archive_dst#"$target_root"/}"
    log "Staged $archive_count container image archive(s) for first-boot preload at ${display_archive_dst}."
    warn "Image preload only avoids registry pulls. Use a pre-provisioned image tagged as ${image} to also avoid apt/NodeSource/Astral/uv downloads."
  else
    warn "No container image archives found in $archive_src."
    warn "To prewarm, place docker/podman image archives there before bootstrap, e.g.: docker save ${image} -o data/container-images/hermes-agent-base.tar"
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

  # ── v2: Find hermes-bootstrap on the stable USB mount ───────────────────
  # auto_live passes /run/hermes-usb/hermes-bootstrap here before /mnt is used
  # for the target root. Prefer that stable source and avoid probing random
  # target/internal partitions after partitioning.
  log "Looking for hermes-bootstrap source..."
  local found_src=""
  if [[ -d "$bootstrap_src" ]]; then
    found_src="$bootstrap_src"
    log "Using source passed by autodeploy: $found_src"
  elif [[ -d /run/hermes-usb/hermes-bootstrap ]]; then
    found_src="/run/hermes-usb/hermes-bootstrap"
    log "Found on stable USB mount: $found_src"
  else
    warn "hermes-bootstrap not found on stable mount. Trying NIXOS-BOOT label once..."
    mkdir -p /run/hermes-usb
    mountpoint -q /run/hermes-usb || mount LABEL=NIXOS-BOOT /run/hermes-usb 2>/dev/null || true
    if [[ -d /run/hermes-usb/hermes-bootstrap ]]; then
      found_src="/run/hermes-usb/hermes-bootstrap"
      log "Found after mounting NIXOS-BOOT: $found_src"
    fi
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

  local efi_uuid root_uuid
  efi_uuid=$(blkid -o value -s UUID "$efi_dev" 2>/dev/null || true)
  root_uuid=$(blkid -o value -s UUID "$root_dev" 2>/dev/null || true)
  [[ -n "$efi_uuid" ]] || error "Could not read UUID for target EFI partition $efi_dev"
  [[ -n "$root_uuid" ]] || error "Could not read UUID for target root partition $root_dev"
  log "Target filesystem UUIDs: root=$root_uuid efi=$efi_uuid"
  cat > /mnt/etc/nixos/hermes-target-filesystems.nix << FSEOF
# Generated by hermes-bootstrap during live install.
# These overrides pin / and /boot/efi to the internal target partitions that
# were just partitioned and mounted, avoiding accidental references to the USB
# installer media in nixos-generate-config output.
{ lib, ... }:
{
  fileSystems."/".device = lib.mkForce "/dev/disk/by-uuid/$root_uuid";
  fileSystems."/".fsType = lib.mkForce "ext4";
  fileSystems."/".options = lib.mkForce [ "defaults" "noatime" ];

  fileSystems."/boot/efi".device = lib.mkForce "/dev/disk/by-uuid/$efi_uuid";
  fileSystems."/boot/efi".fsType = lib.mkForce "vfat";
  fileSystems."/boot/efi".options = lib.mkForce [ "defaults" ];
}
FSEOF

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
  cp /mnt/hermes-bootstrap/system/nixos/harness.nix /mnt/etc/nixos/harness.nix
  rm -rf /mnt/etc/nixos/harness-scripts
  cp -r /mnt/hermes-bootstrap/scripts/harness /mnt/etc/nixos/harness-scripts
  # Keep the generated hermes-target-filesystems.nix from above; the checked-in
  # copy is an empty CI/default placeholder and must not overwrite target UUIDs.
  if [[ -f /mnt/hermes-bootstrap/system/nixos/flake.lock ]]; then
    cp /mnt/hermes-bootstrap/system/nixos/flake.lock /mnt/etc/nixos/flake.lock
  fi

  stage_patched_hermes_agent_source /mnt/etc/nixos

  container_mode_preflight \
    /mnt/etc/nixos/deployment-options.nix \
    /mnt \
    /mnt/hermes-bootstrap

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

  # Install the system to the target root. Earlier experiments avoided
  # `nixos-install --flake` because broken intermediate flake states produced
  # misleading eval errors from the live USB. The target is not yet a NixOS
  # installation, so `nixos-enter --root /mnt` cannot be the first install step.
  # Build/install the now-validated flake directly, with sandbox disabled for
  # live-USB compatibility.
  log "Installing NixOS via nixos-install --flake (this takes 10-30 minutes)..."
  nixos-install \
    --root /mnt \
    --flake /mnt/etc/nixos#hermes \
    --no-root-passwd \
    --impure \
    --option sandbox false \
    --option accept-flake-config true

  # ── Post-install: init git repo for state tracking ───────────────────────
  # The minimal NixOS installer environment may not include git. Treat state
  # tracking as optional post-install setup so a successful nixos-install still
  # proceeds to the reboot path.
  local git_cmd=""
  if command -v git >/dev/null 2>&1; then
    git_cmd="git"
  elif [[ -x /mnt/nix/var/nix/profiles/system/sw/bin/git ]]; then
    git_cmd="/mnt/nix/var/nix/profiles/system/sw/bin/git"
  fi

  if [[ -n "$git_cmd" ]]; then
    log "Initializing git state tracking..."
    "$git_cmd" -C /mnt/var/lib/hermes init
    "$git_cmd" -C /mnt/var/lib/hermes config user.email "hermes@localhost"
    "$git_cmd" -C /mnt/var/lib/hermes config user.name "Hermes OS"
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
  else
    warn "git not found in live or installed system profile — skipping optional /var/lib/hermes state repo initialization"
  fi

  log "${GREEN}NixOS installed!${RESET}"
  echo
  echo "Next steps:"
  echo "  1. Set root password: sudo chroot /mnt passwd"
  echo "  2. Unmount and reboot: sudo umount -R /mnt && sudo reboot"
  echo "  3. Remove USB stick after reboot"
  echo
}


# ═══════════════════════════════════════════════════════════════════════════
# LIVE USB AUTODEPLOY
# ═══════════════════════════════════════════════════════════════════════════
autodeploy_log_setup() {
  exec > >(tee -a /tmp/hermes-bootstrap-autodeploy.log) 2>&1
}

detect_internal_disk() {
  local candidates=()
  local dev type rm size label

  # Use lsblk pairs so empty columns do not shift fields.
  while IFS= read -r line; do
    dev=$(sed -n 's/.*PATH="\([^"]*\)".*/\1/p' <<< "$line")
    type=$(sed -n 's/.*TYPE="\([^"]*\)".*/\1/p' <<< "$line")
    rm=$(sed -n 's/.*RM="\([^"]*\)".*/\1/p' <<< "$line")
    size=$(sed -n 's/.*SIZE="\([^"]*\)".*/\1/p' <<< "$line")
    label=$(sed -n 's/.*LABEL="\([^"]*\)".*/\1/p' <<< "$line")
    size="${size:-0}"
    [[ "$type" == "disk" ]] || continue
    [[ "$rm" == "0" ]] || continue
    [[ "$label" == "NIXOS-BOOT" ]] && continue
    # Exclude the boot USB even in VMs where the parent disk may appear non-removable
    # and only the child partition carries LABEL=NIXOS-BOOT.
    if lsblk -nr -o LABEL "$dev" 2>/dev/null | grep -qx 'NIXOS-BOOT'; then
      continue
    fi
    # Ignore tiny/odd virtual media. Physical N150 target should expose one NVMe/eMMC/SATA disk.
    if (( size < 20 * 1024 * 1024 * 1024 )); then
      continue
    fi
    candidates+=("$dev")
  done < <(lsblk -bdn -P -o PATH,TYPE,RM,SIZE,LABEL 2>/dev/null)

  if (( ${#candidates[@]} == 1 )); then
    printf '%s\n' "${candidates[0]}"
    return 0
  fi

  echo ""
  warn "Could not safely auto-select exactly one internal target disk."
  echo "Detected block devices:"
  lsblk -o NAME,PATH,SIZE,TYPE,TRAN,RM,MODEL,LABEL,MOUNTPOINTS
  echo ""
  if (( ${#candidates[@]} > 1 )); then
    warn "Multiple possible internal disks: ${candidates[*]}"
  else
    warn "No suitable non-removable internal disk >=20G found."
  fi
  printf 'Type the internal disk path to ERASE, or blank to abort: '
  read -r dev
  [[ -n "$dev" && -b "$dev" ]] || error "No valid target disk selected."
  printf '%s\n' "$dev"
}

ensure_usb_bootstrap_mounted() {
  # Do not mount under /mnt: bootstrap_nixos mounts the target root at /mnt,
  # which would hide the USB mount and make the source disappear mid-run.
  local usb_mp="/run/hermes-usb"

  if [[ -d "$usb_mp/hermes-bootstrap" ]]; then
    printf '%s\n' "$usb_mp/hermes-bootstrap"
    return 0
  fi

  mkdir -p "$usb_mp"
  if ! mountpoint -q "$usb_mp"; then
    mount LABEL=NIXOS-BOOT "$usb_mp" 2>/dev/null \
      || mount /dev/disk/by-label/NIXOS-BOOT "$usb_mp" 2>/dev/null \
      || true
  fi

  [[ -d "$usb_mp/hermes-bootstrap" ]] \
    || error "Cannot find $usb_mp/hermes-bootstrap on USB label NIXOS-BOOT"
  printf '%s\n' "$usb_mp/hermes-bootstrap"
}

wait_for_hermes_after_reboot_note() {
  cat <<'NOTE'

[HERMES] Install finished. The installed system should now boot from the internal disk.
[HERMES] If firmware returns to the USB menu after reboot, choose the internal disk in BIOS/boot menu.
[HERMES] On the installed system, hermes-agent is enabled as a systemd service and should start automatically.

NOTE
}

auto_live() {
  check_root

  # systemd.run services do not provide an interactive stdin. Attach this
  # process directly to tty1 so WiFi SSID/password prompts are typeable on the
  # physical console. Avoid openvt here: `openvt -w` can finish the child script
  # successfully but then return nonzero with "Couldn't deallocate console N",
  # which makes kernel-command-line.service fail at the end of an otherwise
  # successful deployment.
  if [[ "${HERMES_LIVE_TTY:-0}" != "1" ]] && [[ ! -t 0 ]] && [[ -e /dev/tty1 ]]; then
    export HERMES_LIVE_TTY=1
    chvt 1 2>/dev/null || true
    exec </dev/tty1 >/dev/tty1 2>&1
  fi

  autodeploy_log_setup
  log "${BOLD}Hermes Bootstrap Autodeploy${RESET}"
  log "Log: /tmp/hermes-bootstrap-autodeploy.log"

  local bootstrap_src target_disk
  bootstrap_src=$(ensure_usb_bootstrap_mounted)
  target_disk=$(detect_internal_disk)

  echo ""
  warn "Autodeploy target: $target_disk"
  warn "This will erase the selected internal disk."
  warn "Single internal disk was auto-selected; continuing without another prompt."

  export HERMES_AUTO_CONFIRM=1
  partition_internal "$target_disk"
  bootstrap_nixos "$target_disk" "$bootstrap_src"

  log "Setting a locked root password; interactive root password setup is skipped for appliance-style boot."
  chroot /mnt passwd -l root >/dev/null 2>&1 || true

  wait_for_hermes_after_reboot_note
  sync
  log "Rebooting in 10 seconds. Remove the USB if firmware keeps preferring it."
  sleep 10
  umount -R /mnt 2>/dev/null || true
  reboot
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
  $0 --auto-live                  Auto-detect disk and deploy from live USB
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

  # On target machine: choose "Hermes Bootstrap" from the USB menu.
  # It auto-runs until WiFi credentials or an unsafe disk choice require input.

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
        [[ $# -ge 2 ]] || error "--bootstrap requires SSD device"
        cmd="bootstrap_nixos"; arg1="${2:-}";
        if [[ $# -ge 3 && "${3:-}" != --* ]]; then
          arg2="$3"; shift 3
        else
          arg2=""; shift 2
        fi ;;
      --auto-live)
        cmd="auto_live"; shift ;;
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
    auto_live)
      auto_live ;;
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
