#!/usr/bin/env bash
# Non-destructively update an existing NIXOS-BOOT FAT32 USB for Hermes autodeploy.
# Usage: sudo ./scripts/update-nixos-usb-autodeploy.sh /dev/sdX
set -euo pipefail

USB="${1:-}"
REPO="${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LABEL="${LABEL:-NIXOS-BOOT}"
MNT="${MNT:-/tmp/hermes-nixos-usb-update}"

fail() { echo "ERROR: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "missing required command: $1"; }
part_path() {
  case "$1" in
    *[0-9]) printf '%sp1\n' "$1" ;;
    *) printf '%s1\n' "$1" ;;
  esac
}

[[ -n "$USB" ]] || fail "usage: sudo $0 /dev/sdX"
[[ $EUID -eq 0 ]] || fail "run with sudo/root"
[[ -b "$USB" ]] || fail "$USB is not a block device"
[[ -d "$REPO" ]] || fail "repo not found: $REPO"
for cmd in lsblk blkid mount umount findmnt rsync grep sed sync; do need "$cmd"; done

TRAN=$(lsblk -dn -o TRAN "$USB" | tr -d ' ')
RM=$(lsblk -dn -o RM "$USB" | tr -d ' ')
MODEL=$(lsblk -dn -o MODEL "$USB" | sed 's/[[:space:]]\+$//')
SIZE=$(lsblk -dn -o SIZE "$USB")
[[ "$TRAN" == "usb" && "$RM" == "1" ]] || fail "refusing: $USB is not removable USB (TRAN=$TRAN RM=$RM MODEL=$MODEL)"

PART=$(part_path "$USB")
[[ -b "$PART" ]] || fail "partition not found: $PART"
PART_LABEL=$(blkid -o value -s LABEL "$PART" 2>/dev/null || true)
[[ "$PART_LABEL" == "$LABEL" ]] || fail "expected $PART label $LABEL, got ${PART_LABEL:-none}"

cat <<EOF
About to update existing Hermes/NixOS USB in-place:
  USB:  $USB ($SIZE, $MODEL)
  Part: $PART label=$PART_LABEL
  Repo: $REPO
This does NOT repartition or format. It rewrites /hermes-bootstrap and /EFI/BOOT/grub.cfg.
The USB will include a non-destructive repair option for already-installed Hermes nodes.
EOF
read -r -p "Type YES to continue: " ans
[[ "$ans" == "YES" ]] || fail "aborted"

cleanup() { mountpoint -q "$MNT" && umount "$MNT" || true; }
trap cleanup EXIT
mkdir -p "$MNT"
if ! mountpoint -q "$MNT"; then
  mount "$PART" "$MNT"
fi

[[ -s "$MNT/EFI/BOOT/grub.cfg" ]] || fail "missing existing grub.cfg on USB"
[[ -s "$MNT/boot/bzImage" ]] || fail "missing /boot/bzImage on USB"
[[ -s "$MNT/boot/initrd" ]] || fail "missing /boot/initrd on USB"
[[ -s "$MNT/nixos-minimal.iso" ]] || fail "missing /nixos-minimal.iso on USB"

INIT_PARAM=$(grep -m1 -o 'init=/nix/store/[^ ]*/init' "$MNT/EFI/BOOT/grub.cfg" || true)
[[ -n "$INIT_PARAM" ]] || fail "could not preserve init= parameter from existing grub.cfg"
ISO_ROOT_LABEL=$(grep -m1 -o 'root=LABEL=[^ ]*' "$MNT/EFI/BOOT/grub.cfg" | sed 's/root=LABEL=//; s/[";]//g' || true)
ISO_ROOT_LABEL=${ISO_ROOT_LABEL:-nixos-minimal-24.05-x86_64}

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

echo "== Updated USB menu =="
grep -E "^set default=|^set timeout=|^menuentry" "$MNT/EFI/BOOT/grub.cfg"
for f in \
  /EFI/BOOT/BOOTX64.EFI \
  /EFI/BOOT/grub.cfg \
  /boot/bzImage \
  /boot/initrd \
  /nixos-minimal.iso \
  /hermes-bootstrap/scripts/deploy-hermes.sh \
  /hermes-bootstrap/scripts/repair-installed-hermes.sh; do
  [[ -s "$MNT$f" ]] || fail "missing $f"
  echo "OK $f"
done

umount "$MNT"
trap - EXIT
sync

echo "READY: USB now has Bootstrap, Bootstrap debug, and non-destructive Installed System Repair options."
