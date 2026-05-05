#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
make_script="$repo_root/boot-image/make-boot-image.sh"
flake="$repo_root/system/nixos/flake.nix"
options="$repo_root/system/nixos/deployment-options.nix"
smoke="$repo_root/tests/boot-image-smoke.sh"

assert_contains() {
  local file="$1"
  local pattern="$2"
  if ! grep -Eq -- "$pattern" "$file"; then
    echo "Missing expected pattern in $file: $pattern" >&2
    exit 1
  fi
}

assert_not_contains() {
  local file="$1"
  local pattern="$2"
  if grep -Eq -- "$pattern" "$file"; then
    echo "Unexpected pattern in $file: $pattern" >&2
    exit 1
  fi
}

# Build script hardening: no stale positional OUTPUT parsing, no stale Alpine
# netboot-grsec URLs, explicit matching LTS kernel/modules, UEFI fallback files,
# and partition rescanning for loop-device assembly.
assert_contains "$make_script" '^OUTPUT="hermes-boot\.img"'
assert_contains "$make_script" 'vmlinuz-lts'
assert_contains "$make_script" 'initramfs-lts'
assert_contains "$make_script" 'gzip -dc "\$BASE_INITRAMFS"'
assert_contains "$make_script" 'Base initramfs did not provide /lib/modules'
assert_contains "$make_script" 'losetup --find --show --partscan'
assert_contains "$make_script" 'BOOTX64\.EFI'
assert_contains "$make_script" 'grub-mkstandalone'
assert_contains "$make_script" '/EFI/BOOT/grub\.cfg'
assert_contains "$make_script" 'parted -s "\$LOOPDEV" set 1 esp on'
assert_contains "$make_script" 'Rootfs build did not produce executable /init'
assert_not_contains "$make_script" 'vmlinuz-grsec'
assert_not_contains "$make_script" 'netboot-virt'

# Non-destructive smoke test should inspect a regular image file with mtools,
# not mount a real USB device or write to any /dev/sdX target.
assert_contains "$smoke" 'mdir -i.*@@'
assert_contains "$smoke" 'BOOTX64'
assert_contains "$smoke" 'GRUB.*CFG'
assert_contains "$smoke" 'missing GPT header'
assert_not_contains "$smoke" '/dev/sdX'

# First boot hardening: container mode is explicit and can be disabled for a
# network-independent native first boot. The mutable image is parameterized.
assert_contains "$options" 'containerMode = false;'
assert_contains "$options" 'containerImage = "ubuntu:24\.04";'
assert_contains "$flake" 'container\.enable = deployment\.containerMode;'
assert_contains "$flake" 'container\.image = deployment\.containerImage;'
assert_contains "$flake" 'addToSystemPackages = true;'
