#!/usr/bin/env bash
# Create a NixOS-kernel findiso fallback USB for hermes-bootstrap on Intel N100/Alder Lake-N.
# Destructive: wipes the USB passed as $1.
set -euo pipefail

USB="${1:-}"
ISO="${2:-${ISO:-/home/steve/latest-nixos-minimal-x86_64-linux.iso}}"
REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LABEL="${LABEL:-NIXOS-BOOT}"
MNT="${MNT:-/tmp/nixos-findiso-usb}"
ISO_MNT="${ISO_MNT:-/tmp/nixos-findiso-iso}"

fail() { echo "ERROR: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"; }

[[ -n "$USB" ]] || fail "usage: sudo $0 /dev/sdX [/path/to/nixos-minimal.iso]"
[[ $EUID -eq 0 ]] || fail "run with sudo/root"
[[ -b "$USB" ]] || fail "$USB is not a block device"
[[ -s "$ISO" ]] || fail "NixOS ISO not found/non-empty: $ISO"
[[ -d "$REPO" ]] || fail "repo not found: $REPO"

for cmd in lsblk sgdisk parted mkfs.fat fatlabel mount umount grub-mkimage rsync sha256sum findmnt; do
  need "$cmd"
done

TRAN=$(lsblk -dn -o TRAN "$USB" | tr -d ' ')
RM=$(lsblk -dn -o RM "$USB" | tr -d ' ')
MODEL=$(lsblk -dn -o MODEL "$USB" | sed 's/[[:space:]]\+$//')
SIZE=$(lsblk -dn -o SIZE "$USB")
[[ "$TRAN" == "usb" && "$RM" == "1" ]] || fail "refusing: $USB is not removable USB (TRAN=$TRAN RM=$RM MODEL=$MODEL)"
if lsblk -nr -o MOUNTPOINTS "$USB" | grep -q '/'; then
  lsblk -o NAME,PATH,SIZE,TYPE,TRAN,MODEL,RM,MOUNTPOINTS,FSTYPE,LABEL "$USB" >&2
  fail "refusing: $USB has mounted filesystems"
fi

cat <<EOF
About to DESTROY and rewrite:
  USB:  $USB ($SIZE, $MODEL)
  ISO:  $ISO
  Repo: $REPO
  New label: $LABEL
EOF
read -r -p "Type YES to continue: " ans
[[ "$ans" == "YES" ]] || fail "aborted"

cleanup() {
  mountpoint -q "$MNT" && umount "$MNT" || true
  mountpoint -q "$ISO_MNT" && umount "$ISO_MNT" || true
}
trap cleanup EXIT

mkdir -p "$MNT" "$ISO_MNT"

# Wipe stale Ventoy/GPT metadata and create a single FAT32 ESP.
sgdisk --zap-all "$USB"
dd if=/dev/zero of="$USB" bs=1M count=1 status=none
parted -s "$USB" mklabel gpt
parted -s "$USB" mkpart primary fat32 1MiB 100%
parted -s "$USB" set 1 esp on
partprobe "$USB" || true
sleep 2
PART="${USB}1"
if [[ "$USB" =~ nvme|mmcblk ]]; then
  PART="${USB}p1"
fi
[[ -b "$PART" ]] || fail "partition did not appear: $PART"
mkfs.fat -F 32 "$PART"
fatlabel "$PART" "$LABEL"

mount "$PART" "$MNT"
mkdir -p "$MNT/boot" "$MNT/EFI/BOOT"

mount -o loop,ro "$ISO" "$ISO_MNT"
# NixOS ISO locations have varied; find exactly one kernel/initrd pair.
BZ=$(find "$ISO_MNT" -path '*/boot/bzImage' -type f | head -1)
INITRD=$(find "$ISO_MNT" -path '*/boot/initrd' -type f | head -1)
[[ -s "$BZ" ]] || fail "could not find boot/bzImage inside ISO"
[[ -s "$INITRD" ]] || fail "could not find boot/initrd inside ISO"
cp "$BZ" "$MNT/boot/bzImage"
cp "$INITRD" "$MNT/boot/initrd"
# Reuse the ISO's own stage-2 init path. Without init=..., NixOS stage 1
# reaches /mnt-root but fails with: stage 2 init script (/mnt-root//init) not found.
INIT_PARAM=$(grep -m1 -o 'init=/nix/store/[^ ]*/init' "$ISO_MNT/EFI/boot/grub.cfg")
[[ -n "$INIT_PARAM" ]] || fail "could not extract NixOS init= parameter from ISO grub.cfg"
umount "$ISO_MNT"

cp "$ISO" "$MNT/nixos-minimal.iso"
mkdir -p "$MNT/hermes-bootstrap"
rsync -rt --delete --modify-window=2 \
  --exclude='.git/' \
  --exclude='boot-image/rootfs/' \
  --exclude='boot-image/rootfs-packages/' \
  --exclude='boot-image/aports/' \
  --exclude='boot-image/*.img' \
  --exclude='boot-image/boot-image.cpio.gz' \
  --exclude='system/nixos/hermes-agent-src/' \
  --exclude='usb-backup-2026-05-01/' \
  "$REPO/" "$MNT/hermes-bootstrap/"

grub-mkimage \
  -p /EFI/BOOT \
  -o "$MNT/EFI/BOOT/BOOTX64.EFI" \
  -O x86_64-efi \
  fat part_gpt part_msdos search search_fs_uuid search_label linux font efifwsetup loopback configfile iso9660 squash4 test cat echo ls regexp normal

ISO_ROOT_LABEL=$(blkid -o value -s LABEL "$ISO" 2>/dev/null || true)
ISO_ROOT_LABEL=${ISO_ROOT_LABEL:-nixos-minimal-24.05-x86_64}

cat > "$MNT/EFI/BOOT/grub.cfg" <<GRUBCFG
set timeout=15
set default=2
search --set=root --label NIXOS-BOOT
set iso_path=/nixos-minimal.iso
set isoboot="findiso=\${iso_path}"
set init_param="$INIT_PARAM"
set iso_root="root=LABEL=$ISO_ROOT_LABEL"
menuentry 'Hermes Bootstrap / Reinstall (DESTRUCTIVE)' {
  terminal_output console
  linux (\$root)/boot/bzImage \${isoboot} \${init_param} \${iso_root} boot.shell_on_fail nohibernate loglevel=4 module_blacklist=i915 systemd.unit=kernel-command-line.target systemd.run="/run/current-system/sw/bin/mkdir -p /run/hermes-usb" systemd.run="/run/current-system/sw/bin/mount LABEL=NIXOS-BOOT /run/hermes-usb" systemd.run="/run/current-system/sw/bin/env PATH=/run/current-system/sw/bin:/bin:/usr/bin /run/current-system/sw/bin/bash /run/hermes-usb/hermes-bootstrap/scripts/deploy-hermes.sh --auto-live" systemd.run_success_action=none systemd.run_failure_action=none
  initrd (\$root)/boot/initrd
}
menuentry 'Hermes Bootstrap Debug / Reinstall (DESTRUCTIVE)' {
  terminal_output console
  linux (\$root)/boot/bzImage \${isoboot} \${init_param} \${iso_root} boot.shell_on_fail nohibernate loglevel=7 debug module_blacklist=i915 console=tty0 console=ttyS0,115200n8 systemd.unit=kernel-command-line.target systemd.run="/run/current-system/sw/bin/mkdir -p /run/hermes-usb" systemd.run="/run/current-system/sw/bin/mount LABEL=NIXOS-BOOT /run/hermes-usb" systemd.run="/run/current-system/sw/bin/env PATH=/run/current-system/sw/bin:/bin:/usr/bin /run/current-system/sw/bin/bash /run/hermes-usb/hermes-bootstrap/scripts/deploy-hermes.sh --auto-live" systemd.run_success_action=none systemd.run_failure_action=none
  initrd (\$root)/boot/initrd
}
menuentry 'Hermes Repair Installed System (non-destructive)' {
  terminal_output console
  linux (\$root)/boot/bzImage \${isoboot} \${init_param} \${iso_root} boot.shell_on_fail nohibernate loglevel=4 module_blacklist=i915 systemd.unit=kernel-command-line.target systemd.run="/run/current-system/sw/bin/mkdir -p /run/hermes-usb" systemd.run="/run/current-system/sw/bin/mount LABEL=NIXOS-BOOT /run/hermes-usb" systemd.run="/run/current-system/sw/bin/env PATH=/run/current-system/sw/bin:/bin:/usr/bin /run/current-system/sw/bin/bash /run/hermes-usb/hermes-bootstrap/scripts/repair-installed-hermes.sh --auto-live" systemd.run_success_action=none systemd.run_failure_action=none
  initrd (\$root)/boot/initrd
}
GRUBCFG

if grep -q '\\\\"' "$MNT/EFI/BOOT/grub.cfg"; then
  fail "generated grub.cfg contains literal backslash-quote (\\\") in systemd.run; this causes systemd 'Executable name contains special characters'"
fi
if grep -q '\\\\/run/current-system' "$MNT/EFI/BOOT/grub.cfg"; then
  fail "generated grub.cfg contains literal escaped slash (\\/run); systemd will reject ExecStart"
fi
if grep -q "'systemd.run=" "$MNT/EFI/BOOT/grub.cfg"; then
  fail "generated grub.cfg single-quotes systemd.run tokens; systemd-run-generator then quotes the entire command as the executable"
fi
if command -v systemd-run-generator >/dev/null 2>&1 || [[ -x /usr/lib/systemd/system-generators/systemd-run-generator ]]; then
  GEN=$(command -v systemd-run-generator || printf '%s\n' /usr/lib/systemd/system-generators/systemd-run-generator)
  while IFS= read -r CMDLINE; do
    [[ -n "$CMDLINE" ]] || continue
    TMP_GEN=$(mktemp -d)
    SYSTEMD_PROC_CMDLINE="$CMDLINE" "$GEN" "$TMP_GEN" /tmp /tmp >/dev/null 2>&1 || true
    if grep -qE '^ExecStart=\"|^ExecStart=\\\\/' "$TMP_GEN/kernel-command-line.service" 2>/dev/null; then
      sed -n '1,80p' "$TMP_GEN/kernel-command-line.service" >&2 || true
      rm -rf "$TMP_GEN"
      fail "systemd-run-generator would emit an invalid ExecStart from this grub.cfg"
    fi
    rm -rf "$TMP_GEN"
  done < <(sed -nE 's/^[[:space:]]*linux[[:space:]]+[^[:space:]]+[[:space:]]+//p' "$MNT/EFI/BOOT/grub.cfg")
fi

sync

echo "== Verify staged USB =="
df -h "$MNT"
for f in \
  /EFI/BOOT/BOOTX64.EFI \
  /EFI/BOOT/grub.cfg \
  /boot/bzImage \
  /boot/initrd \
  /nixos-minimal.iso \
  /hermes-bootstrap/system/nixos/flake.nix \
  /hermes-bootstrap/system/nixos/flake.lock \
  /hermes-bootstrap/scripts/repair-installed-hermes.sh; do
  [[ -s "$MNT$f" ]] || fail "missing $f"
  echo "OK $f"
done
sha256sum "$ISO" "$MNT/nixos-minimal.iso"

umount "$MNT"
trap - EXIT
sync

echo "READY: $USB is now a NixOS findiso fallback USB."
echo "On the mini-PC, choose: Hermes Repair Installed System for non-destructive state/service repair, or Bootstrap to reinstall."
