#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# hermes-bootstrap boot-image build script
# ═══════════════════════════════════════════════════════════════════════════
# Builds hermes-boot.img: a minimal Alpine-based bootable image.
# The resulting .img file is written directly to USB via `dd`.
#
# USAGE:
#   sudo ./make-boot-image.sh [--size 80M] [--output hermes-boot.img]
#
# REQUIREMENTS:
#   - Docker (for clean Alpine build environment)
#   - OR: apk, mkinitfs, dosfstools, syslinux on Alpine Linux
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OVERLAY="$SCRIPT_DIR/overlay"
OUTPUT="${2:-hermes-boot.img}"
SIZE="${SIZE:-80M}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; RESET='\033[0m'
log() { echo -e "${GREEN}[BUILD]${RESET} $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $*"; }
error() { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }

need() { command -v "$1" &>/dev/null || error "Required: $1 (not found)"; }

# ─── Validate requirements ─────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
  error "Must be run as root (sudo)"
fi

# ─── Parse args ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --size) SIZE="$2"; shift 2 ;;
    --output) OUTPUT="$2"; shift 2 ;;
    *) shift ;;
  esac
done

log "${BOLD}Building hermes-bootstrap boot image${RESET}"
log "Output: $OUTPUT"
log "Size: $SIZE"

# ─── Detect builder (Docker vs native Alpine) ───────────────────────────────
if command -v docker &>/dev/null && docker info &>/dev/null; then
  BUILDER=docker
  log "Builder: Docker"
elif [[ -f /etc/alpine-release ]]; then
  BUILDER=apk
  log "Builder: Native Alpine"
else
  BUILDER=docker
  log "Builder: Docker (fallback)"
fi

# ─── Build the initrd + kernel ────────────────────────────────────────────
INITRD="$SCRIPT_DIR/aports/initrd.cpio.gz"
KERNEL="$SCRIPT_DIR/aports/vmlinuz"

if [[ ! -f "$INITRD" || ! -f "$KERNEL" ]]; then
  log "First run — downloading Alpine kernel + initrd..."
  mkdir -p "$SCRIPT_DIR/aports"
  cd "$SCRIPT_DIR/aports"

  # Download the Alpine extended initrd (contains all needed modules)
  ALPINE_VER="3.19"
  wget -q "https://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VER}/releases/x86_64/netboot-$(cat /etc/alpine-release 2>/dev/null || echo "${ALPINE_VER}")/vmlinuz-grsec" \
    -O vmlinuz 2>/dev/null || \
  wget -q "https://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VER}/releases/x86_64/alpine-virt-${ALPINE_VER}-x86_64.iso" -O /tmp/alpine.iso

  # Extract kernel + initrd from ISO via Docker
  if [[ -f /tmp/alpine.iso ]]; then
    log "Extracting kernel + initrd from ISO..."
    docker run --rm -v "$SCRIPT_DIR/aports:/out" alpine:${ALPINE_VER} sh -c "
      apk add -U alpine-conf >/dev/null 2>&1
      setup-disk -m iso /tmp/alpine.iso /out 2>/dev/null || true
    " || true
  fi

  # Fallback: download standard netboot
  if [[ ! -f "$KERNEL" ]]; then
    wget -q "https://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VER}/releases/x86_64/netboot-virt/vmlinuz-grsec" -O "$KERNEL"
  fi
  if [[ ! -f "$INITRD" ]]; then
    wget -q "https://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VER}/releases/x86_64/netboot-virt/initramfs-grsec" -O "$INITRD"
  fi

  cd "$SCRIPT_DIR"
  log "Alpine kernel + initrd downloaded."
fi

# ─── Build rootfs overlay ─────────────────────────────────────────────────
ROOTFS="$SCRIPT_DIR/rootfs"
log "Building rootfs overlay..."

if [[ -d "$ROOTFS" ]]; then
  log "Using existing rootfs (delete to rebuild)"
else
  mkdir -p "$ROOTFS"

  if [[ "$BUILDER" == "docker" ]]; then
    log "Creating rootfs via Docker (Alpine ${ALPINE_VER})..."
    docker run --rm \
      -v "$OVERLAY:/overlay:ro" \
      -v "$ROOTFS:/rootfs" \
      alpine:${ALPINE_VER} sh - <<'ROOTFS_SCRIPT'
set -e
apk --root /rootfs init --force /etc/apk/repositories <<EOF
https://dl-cdn.alpinelinux.org/alpine/v3.19/main
https://dl-cdn.alpinelinux.org/alpine/v3.19/community
EOF
apk --root /rootfs add --force-refs \
  alpine-baselayout \
  alpine-conf \
  alpine-baselayout-data \
  busybox \
  bash \
  openssh \
  wpa_supplicant \
  wpa_passphrase \
  dhcpcd \
  iw \
  iputils \
  util-linux \
  parted \
  e2fsprogs \
  dosfstools \
  coreutils \
  bash \
  curl \
  wget \
  git \
  nix \
  openssl \
  ca-certificates \
  2>/dev/null || true

# Copy overlay files (custom scripts, configs)
cp -r /overlay/* /rootfs/

# Install WiFi regulatory database
apk --root /rootfs add iw 2>/dev/null || true

# Create essential device nodes
mkdir -p /rootfs/dev /rootfs/proc /rootfs/sys /rootfs/run
ROOTFS_SCRIPT
  else
    log "Creating rootfs natively (apk)..."
    apk --root "$ROOTFS" init --force
    apk --root "$ROOTFS" add --force-refs \
      alpine-baselayout busybox bash wpa_supplicant dhcpcd iw \
      parted e2fsprogs dosfstools coreutils curl wget git openssl ca-certificates \
      2>/dev/null || true
    cp -r "$OVERLAY"/* "$ROOTFS"/ 2>/dev/null || true
  fi

  log "Rootfs created: $(du -sh "$ROOTFS" 2>/dev/null | cut -f1)"
fi

# ─── Package the initramfs ───────────────────────────────────────────────
CPIO="$SCRIPT_DIR/boot-image.cpio.gz"
log "Packaging initramfs..."

if [[ -f "$CPIO" ]]; then
  rm "$CPIO"
fi

# Build initramfs from rootfs
(
  cd "$ROOTFS"
  find . -print0 | sort -z | cpio --null -H newc -R 0:0 -o 2>/dev/null | gzip -9 > "$CPIO"
)

log "Initramfs: $(du -sh "$CPIO" | cut -f1)"

# ─── Assemble the disk image ──────────────────────────────────────────────
log "Assembling disk image (${SIZE})..."

dd if=/dev/zero of="$OUTPUT" bs=1 count=0 seek="${SIZE}" 2>/dev/null
LOOPDEV=$(losetup --find --show "$OUTPUT" 2>/dev/null || echo "")

if [[ -z "$LOOPDEV" ]]; then
  warn "Loopback failed — building as file only"
  # Fallback: just bundle kernel + initrd + overlay into a tarball
  mkdir -p "$(dirname "$OUTPUT")"
  tar czf "${OUTPUT%.img}.tar.gz" \
    "$KERNEL" "$CPIO" "$OVERLAY"/auto-deploy.sh \
    -C "$OVERLAY" . 2>/dev/null || true
  log "Built: ${OUTPUT%.img}.tar.gz"
  exit 0
fi

parted -s "$LOOPDEV" mklabel gpt
parted -s "$LOOPDEV" mkpart primary fat32 1MiB 100%
parted -s "$LOOPDEV" set 1 boot on 2>/dev/null || true

mkfs.fat -F 32 -n HERMES-BOOT "${LOOPDEV}p1"

MPoint=$(mktemp -d)
mount "${LOOPDEV}p1" "$MPoint"

# Copy kernel + initrd
cp "$KERNEL" "$MPoint/vmlinuz"
cp "$CPIO" "$MPoint/initramfs.gz"

# Copy overlay (auto-deploy.sh, scripts, configs)
cp -r "$OVERLAY"/* "$MPoint/"

# Install SYSLINUX (for direct USB boot without BIOS dependency)
if command -v syslinux &>/dev/null; then
  dd if=/usr/share/syslinux/mbr.bin of="$LOOPDEV" bs=440 count=1 conv=notrunc 2>/dev/null || \
  dd if=/usr/share/syslinux/mbr.bin of="$LOOPDEV" bs=440 count=1 2>/dev/null || true
  syslinux --install "${LOOPDEV}p1" 2>/dev/null || true
fi

# Create a minimal boot config for SYSLINUX
cat > "$MPoint/syslinux.cfg" <<'SYSLINUX'
DEFAULT hermes
LABEL hermes
  KERNEL vmlinuz
  INITRD initramfs.gz
  APPEND root=/dev/ram0 modules=ext4,sd-mod,usb-storage quiet
TIMEOUT 30
PROMPT 1
SYSLINUX

sync
umount "$MPoint"
losetup -d "$LOOPDEV" 2>/dev/null || true

log "${GREEN}Boot image built: $OUTPUT ($(du -sh "$OUTPUT" | cut -f1))${RESET}"
log ""
log "To write to USB:"
log "  sudo dd if=$OUTPUT of=/dev/sdX bs=4M status=progress conv=fsync"
log ""
log "Then copy hermes-bootstrap/ + NixOS ISO to the USB data partition."
