#!/usr/bin/env bash
set -euo pipefail

image="${1:-boot-image/hermes-boot.img}"
offset="${BOOT_IMAGE_OFFSET:-1048576}"
min_size=$((120 * 1024 * 1024))

fail() {
  echo "boot-image smoke failed: $*" >&2
  exit 1
}

need() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

[[ -f "$image" ]] || fail "image not found: $image"
need python3
need mdir
need mtype
need mcopy

size=$(python3 - "$image" <<'PY'
import os, sys
print(os.path.getsize(sys.argv[1]))
PY
)
[[ "$size" -ge "$min_size" ]] || fail "image too small: ${size} bytes; expected at least ${min_size}"

python3 - "$image" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
data = p.read_bytes()[:4096]
if not data or set(data) == {0}:
    raise SystemExit('first 4KiB are all zero; missing partition/boot metadata')
if data[510:512] != b'\x55\xaa':
    raise SystemExit('missing MBR boot signature 55aa at bytes 510-511')
# GPT header normally starts at LBA1 for the generated image.
if data[512:520] != b'EFI PART':
    raise SystemExit('missing GPT header at LBA1')
print('partition metadata: ok')
PY

mdir -i "${image}@@${offset}" ::/ >/tmp/hermes-boot-mdir-root.$$ || fail "cannot read FAT partition at offset ${offset}"
tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"; rm -f /tmp/hermes-boot-mdir-root.$$ /tmp/hermes-boot-mdir-efi.$$ /tmp/hermes-boot-syslinux.$$ /tmp/hermes-boot-grub.$$' EXIT

for path in 'VMLINUZ' 'INITRA~1[[:space:]]+GZ|initramfs\.gz' 'AUTO-D~1[[:space:]]+SH|auto-deploy\.sh' 'SYSLINUX[[:space:]]+CFG|syslinux\.cfg' 'EFI'; do
  grep -Eqi "$path" /tmp/hermes-boot-mdir-root.$$ || fail "missing root FAT entry matching $path"
done

mdir -i "${image}@@${offset}" ::/EFI/BOOT >/tmp/hermes-boot-mdir-efi.$$ || fail "cannot list /EFI/BOOT"
for path in 'BOOTX64[[:space:]]+EFI|BOOTX64\.EFI' 'GRUB[[:space:]]+CFG|grub\.cfg'; do
  grep -Eqi "$path" /tmp/hermes-boot-mdir-efi.$$ || fail "missing /EFI/BOOT entry matching $path"
done

mtype -i "${image}@@${offset}" ::/syslinux.cfg >/tmp/hermes-boot-syslinux.$$ || fail "cannot read syslinux.cfg"
mtype -i "${image}@@${offset}" ::/EFI/BOOT/grub.cfg >/tmp/hermes-boot-grub.$$ || fail "cannot read EFI grub.cfg"
mcopy -i "${image}@@${offset}" ::/EFI/BOOT/BOOTX64.EFI "$tmpdir/BOOTX64.EFI" || fail "cannot copy UEFI BOOTX64.EFI for validation"
python3 - "$tmpdir/BOOTX64.EFI" <<'PY' || fail "BOOTX64.EFI is not a valid-looking PE/COFF EFI binary"
import pathlib, sys
p = pathlib.Path(sys.argv[1])
data = p.read_bytes()
if len(data) < 1024 or data[:2] != b'MZ' or b'PE\x00\x00' not in data[:512]:
    raise SystemExit(1)
PY

grep -q '/vmlinuz' /tmp/hermes-boot-syslinux.$$ || fail "syslinux.cfg does not reference /vmlinuz"
grep -q '/initramfs.gz' /tmp/hermes-boot-syslinux.$$ || fail "syslinux.cfg does not reference /initramfs.gz"
grep -q 'linux /vmlinuz' /tmp/hermes-boot-grub.$$ || fail "grub.cfg does not boot /vmlinuz"
grep -q 'initrd /initramfs.gz' /tmp/hermes-boot-grub.$$ || fail "grub.cfg does not boot /initramfs.gz"

echo "boot-image smoke: ok ($image, ${size} bytes)"
