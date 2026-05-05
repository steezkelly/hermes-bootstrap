#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# hermes-bootstrap boot-image build script
# ═══════════════════════════════════════════════════════════════════════════
# Builds hermes-boot.img: a minimal Alpine-based bootable USB disk image.
# The resulting .img file is written directly to USB via `dd` by an operator.
#
# This script only writes regular files and loop devices created from those
# files. It never writes to a host block device such as /dev/sdX.
#
# USAGE:
#   sudo ./make-boot-image.sh [--size 256M] [--output hermes-boot.img]
#
# REQUIREMENTS:
#   - Docker (recommended, for a clean Alpine build environment)
#   - Host tools: cpio, gzip, parted, losetup, mkfs.fat, mount
#   - Optional: syslinux for BIOS boot, grub-mkstandalone for UEFI boot
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OVERLAY="$SCRIPT_DIR/overlay"
OUTPUT="hermes-boot.img"
SIZE="${SIZE:-256M}"
ALPINE_VER="${ALPINE_VER:-3.19}"
FORCE_ROOTFS="${FORCE_ROOTFS:-0}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; RESET='\033[0m'
log() { echo -e "${GREEN}[BUILD]${RESET} $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET} $*"; }
error() { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }

need() { command -v "$1" &>/dev/null || error "Required: $1 (not found)"; }

# ─── Parse args ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --size) SIZE="${2:?--size needs a value}"; shift 2 ;;
    --output) OUTPUT="${2:?--output needs a value}"; shift 2 ;;
    --force-rootfs) FORCE_ROOTFS=1; shift ;;
    -h|--help)
      sed -n '1,32p' "$0"
      exit 0
      ;;
    *) error "Unknown argument: $1" ;;
  esac
done

if [[ $EUID -ne 0 ]]; then
  error "Must be run as root (sudo) because loop-device assembly requires mount privileges"
fi

need cpio
need gzip
need curl
need parted
need losetup
need mount
need umount
need mkfs.fat

mkdir -p "$(dirname "$OUTPUT")"

log "${BOLD}Building hermes-bootstrap boot image${RESET}"
log "Output: $OUTPUT"
log "Size: $SIZE"
log "Alpine: $ALPINE_VER"

# ─── Detect builder (Docker vs native Alpine) ───────────────────────────────
if command -v docker &>/dev/null && docker info &>/dev/null; then
  BUILDER=docker
  log "Builder: Docker"
elif [[ -f /etc/alpine-release ]] && command -v apk &>/dev/null; then
  BUILDER=apk
  log "Builder: Native Alpine"
else
  error "Docker is not running and this host is not Alpine with apk available"
fi

ROOTFS="$SCRIPT_DIR/rootfs"
PKG_ROOTFS="$SCRIPT_DIR/rootfs-packages"
APORTS="$SCRIPT_DIR/aports"
KERNEL="$APORTS/vmlinuz-lts"
BASE_INITRAMFS="$APORTS/initramfs-lts"
CPIO="$SCRIPT_DIR/boot-image.cpio.gz"

fetch_nonempty() {
  local url="$1"
  local dest="$2"
  local tmp="${dest}.tmp"
  if [[ -s "$dest" ]]; then
    return 0
  fi
  log "Downloading $(basename "$dest")..."
  rm -f "$tmp"
  curl -fL --retry 3 --connect-timeout 20 "$url" -o "$tmp"
  [[ -s "$tmp" ]] || error "Downloaded file is empty: $url"
  mv "$tmp" "$dest"
}

cleanup_container() {
  if [[ -n "${ROOTFS_CONTAINER:-}" ]]; then
    docker rm -f "$ROOTFS_CONTAINER" >/dev/null 2>&1 || true
  fi
}

cleanup_loop() {
  local rc=$?
  if [[ -n "${MPoint:-}" && -d "${MPoint:-}" ]]; then
    mountpoint -q "$MPoint" && umount "$MPoint" || true
    rmdir "$MPoint" 2>/dev/null || true
  fi
  if [[ -n "${LOOPDEV:-}" ]]; then
    losetup -d "$LOOPDEV" 2>/dev/null || true
  fi
  exit "$rc"
}

# ─── Build rootfs on top of Alpine netboot LTS initramfs ───────────────────
mkdir -p "$APORTS"
fetch_nonempty "https://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VER}/releases/x86_64/netboot/vmlinuz-lts" "$KERNEL"
fetch_nonempty "https://dl-cdn.alpinelinux.org/alpine/v${ALPINE_VER}/releases/x86_64/netboot/initramfs-lts" "$BASE_INITRAMFS"

if [[ "$FORCE_ROOTFS" == "1" || ! -d "$ROOTFS" || ! -x "$ROOTFS/init" ]]; then
  log "Building Alpine rootfs overlay with deployment tools..."
  rm -rf "$ROOTFS" "$PKG_ROOTFS"
  mkdir -p "$ROOTFS" "$PKG_ROOTFS"

  log "Unpacking Alpine netboot initramfs base..."
  (
    cd "$ROOTFS"
    gzip -dc "$BASE_INITRAMFS" | cpio -idmu --quiet
  )

  if [[ "$BUILDER" == "docker" ]]; then
    ROOTFS_CONTAINER="hermes-bootstrap-rootfs-$$"
    trap cleanup_container EXIT
    docker rm -f "$ROOTFS_CONTAINER" >/dev/null 2>&1 || true
    docker run --name "$ROOTFS_CONTAINER" \
      -v "$OVERLAY:/overlay:ro" \
      "alpine:${ALPINE_VER}" sh -c '
set -eu
apk add --no-cache \
  alpine-baselayout \
  alpine-conf \
  busybox \
  bash \
  openssh \
  wpa_supplicant \
  dhcpcd \
  iw \
  iputils \
  util-linux \
  parted \
  e2fsprogs \
  dosfstools \
  coreutils \
  curl \
  wget \
  git \
  openssl \
  ca-certificates
cp -a /overlay/. /
mkdir -p /dev /proc /sys /run /tmp /root
chmod 1777 /tmp
chmod +x /auto-deploy.sh /usr/local/bin/hw-detect /usr/local/bin/wifi-setup 2>/dev/null || true
cat > /init <<'INIT_EOF'
#!/bin/sh
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
mount -t devtmpfs devtmpfs /dev 2>/dev/null || true
mkdir -p /dev/pts /proc /sys /run /tmp
mount -t devpts devpts /dev/pts 2>/dev/null || true
mount -t proc proc /proc 2>/dev/null || true
mount -t sysfs sysfs /sys 2>/dev/null || true
mount -t tmpfs tmpfs /run 2>/dev/null || true
chmod 1777 /tmp
exec </dev/console >/dev/console 2>&1
printf '\nHermes Bootstrap initramfs starting...\n'
if [ -x /auto-deploy.sh ]; then
  /auto-deploy.sh
fi
printf '\nHermes Bootstrap dropped to emergency shell.\n'
exec /bin/sh
INIT_EOF
chmod +x /init
'
    docker export "$ROOTFS_CONTAINER" | tar -C "$PKG_ROOTFS" -xf -
    docker rm "$ROOTFS_CONTAINER" >/dev/null
    ROOTFS_CONTAINER=""
    trap - EXIT
    cp -a "$PKG_ROOTFS"/. "$ROOTFS"/
    chmod +x "$ROOTFS/init" "$ROOTFS/auto-deploy.sh" "$ROOTFS/usr/local/bin/hw-detect" "$ROOTFS/usr/local/bin/wifi-setup" 2>/dev/null || true
    rm -rf "$PKG_ROOTFS"
  else
    apk --root "$PKG_ROOTFS" --initdb add --no-cache \
      alpine-baselayout alpine-conf busybox bash openssh wpa_supplicant dhcpcd iw \
      iputils util-linux parted e2fsprogs dosfstools coreutils curl wget git \
      openssl ca-certificates
    cp -a "$PKG_ROOTFS"/. "$ROOTFS"/
    cp -a "$OVERLAY"/. "$ROOTFS"/
    cat > "$ROOTFS/init" <<'INIT_EOF'
#!/bin/sh
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
mount -t devtmpfs devtmpfs /dev 2>/dev/null || true
mkdir -p /dev/pts /proc /sys /run /tmp
mount -t devpts devpts /dev/pts 2>/dev/null || true
mount -t proc proc /proc 2>/dev/null || true
mount -t sysfs sysfs /sys 2>/dev/null || true
mount -t tmpfs tmpfs /run 2>/dev/null || true
chmod 1777 /tmp
exec </dev/console >/dev/console 2>&1
printf '\nHermes Bootstrap initramfs starting...\n'
if [ -x /auto-deploy.sh ]; then
  /auto-deploy.sh
fi
printf '\nHermes Bootstrap dropped to emergency shell.\n'
exec /bin/sh
INIT_EOF
    chmod +x "$ROOTFS/init" "$ROOTFS/auto-deploy.sh" || true
  fi

  [[ -x "$ROOTFS/init" ]] || error "Rootfs build did not produce executable /init"
  [[ -d "$ROOTFS/lib/modules" ]] || error "Base initramfs did not provide /lib/modules"
  log "Rootfs created: $(du -sh "$ROOTFS" 2>/dev/null | cut -f1)"
else
  log "Using existing rootfs (set FORCE_ROOTFS=1 or --force-rootfs to rebuild)"
fi

[[ -s "$KERNEL" ]] || error "Kernel missing or empty: $KERNEL"

# ─── Package the initramfs ───────────────────────────────────────────────
log "Packaging initramfs..."
rm -f "$CPIO"
(
  cd "$ROOTFS"
  find . -print0 | sort -z | cpio --null -H newc -R 0:0 -o 2>/dev/null | gzip -9 > "$CPIO"
)
[[ -s "$CPIO" ]] || error "Initramfs was not created"
log "Kernel: $(du -sh "$KERNEL" | cut -f1)"
log "Initramfs: $(du -sh "$CPIO" | cut -f1)"

# ─── Assemble the disk image ──────────────────────────────────────────────
log "Assembling disk image (${SIZE})..."
rm -f "$OUTPUT"
truncate -s "$SIZE" "$OUTPUT"

LOOPDEV=""
MPoint=""
trap cleanup_loop EXIT
LOOPDEV=$(losetup --find --show --partscan "$OUTPUT")

parted -s "$LOOPDEV" mklabel gpt
parted -s "$LOOPDEV" mkpart ESP fat32 1MiB 100%
parted -s "$LOOPDEV" set 1 esp on
parted -s "$LOOPDEV" set 1 boot on
partprobe "$LOOPDEV" 2>/dev/null || true
sleep 1

PARTDEV="${LOOPDEV}p1"
if [[ ! -b "$PARTDEV" ]]; then
  partx -a "$LOOPDEV" 2>/dev/null || true
  sleep 1
fi
[[ -b "$PARTDEV" ]] || error "Partition device did not appear: $PARTDEV"

mkfs.fat -F 32 -n HERMES-BOOT "$PARTDEV"

MPoint=$(mktemp -d)
mount "$PARTDEV" "$MPoint"

# Copy kernel + initrd
cp "$KERNEL" "$MPoint/vmlinuz"
cp "$CPIO" "$MPoint/initramfs.gz"

# Copy overlay (auto-deploy.sh, scripts, configs)
cp -R --no-preserve=ownership "$OVERLAY"/. "$MPoint/"

# BIOS boot via SYSLINUX. This is best-effort; UEFI below is mandatory.
if command -v syslinux &>/dev/null; then
  for mbr in \
    /usr/lib/syslinux/mbr/mbr.bin \
    /usr/share/syslinux/mbr.bin \
    /usr/lib/SYSLINUX/mbr.bin; do
    if [[ -f "$mbr" ]]; then
      dd if="$mbr" of="$LOOPDEV" bs=440 count=1 conv=notrunc 2>/dev/null || true
      break
    fi
  done
  syslinux --install "$PARTDEV" 2>/dev/null || warn "SYSLINUX install failed; UEFI boot files will still be created"
else
  warn "syslinux not found; BIOS boot not installed"
fi

cat > "$MPoint/syslinux.cfg" <<'SYSLINUX'
DEFAULT hermes
LABEL hermes
  KERNEL /vmlinuz
  INITRD /initramfs.gz
  APPEND root=/dev/ram0 modules=ext4,sd-mod,usb-storage,nvme console=tty1 quiet
TIMEOUT 30
PROMPT 1
SYSLINUX

# UEFI boot via fallback path /EFI/BOOT/BOOTX64.EFI.
mkdir -p "$MPoint/EFI/BOOT"
cat > "$MPoint/EFI/BOOT/grub.cfg" <<'GRUBCFG'
search --set=root --label HERMES-BOOT
set timeout=5
set default=0
menuentry "Hermes Bootstrap" {
    linux /vmlinuz root=/dev/ram0 modules=ext4,sd-mod,usb-storage,nvme console=tty1 quiet
    initrd /initramfs.gz
}
GRUBCFG

if command -v grub-mkstandalone &>/dev/null; then
  grub-mkstandalone \
    -O x86_64-efi \
    -o "$MPoint/EFI/BOOT/BOOTX64.EFI" \
    --modules="part_gpt part_msdos fat normal linux search search_label search_fs_uuid configfile" \
    "boot/grub/grub.cfg=$MPoint/EFI/BOOT/grub.cfg" >/dev/null
else
  warn "grub-mkstandalone not found; UEFI BOOTX64.EFI was not created"
fi

[[ -s "$MPoint/EFI/BOOT/BOOTX64.EFI" ]] || error "UEFI BOOTX64.EFI missing"
[[ -s "$MPoint/EFI/BOOT/grub.cfg" ]] || error "UEFI grub.cfg missing"

sync
umount "$MPoint"
rmdir "$MPoint"
MPoint=""
losetup -d "$LOOPDEV" 2>/dev/null || true
LOOPDEV=""
trap - EXIT

log "${GREEN}Boot image built: $OUTPUT ($(du -sh "$OUTPUT" | cut -f1))${RESET}"
log ""
log "To inspect non-destructively:"
log "  tests/boot-image-smoke.sh $OUTPUT"
log ""
log "To write to USB (operator-run, destructive):"
log "  sudo dd if=$OUTPUT of=/dev/sdX bs=4M status=progress conv=fsync"
