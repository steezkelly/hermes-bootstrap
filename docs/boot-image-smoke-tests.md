# Boot image smoke tests

`boot-image/make-boot-image.sh` builds `boot-image/hermes-boot.img`, an Alpine-based regular disk image with a GPT partition table and a FAT32 EFI System Partition starting at 1 MiB.

The build path is intentionally separate from the manual NixOS installer path. It is still hardware-sensitive, so validate it as an artifact before writing it to any USB stick.

## Fresh build

```bash
cd /path/to/hermes-bootstrap
sudo ./boot-image/make-boot-image.sh --size 256M --output boot-image/hermes-boot.img --force-rootfs
```

Current expected properties:

- Alpine v3.19 LTS netboot kernel: `aports/vmlinuz-lts`
- Alpine v3.19 LTS netboot initramfs used as the module-bearing base
- Additional rootfs overlay with `bash`, WiFi tools, DHCP, partitioning tools, curl/wget/git, and bootstrap scripts
- Custom `/init` that mounts basic pseudo-filesystems and runs `/auto-deploy.sh`
- GPT + single FAT32 ESP labelled `HERMES-BOOT`
- BIOS best-effort files: `syslinux.cfg` plus SYSLINUX MBR/VBR when host tools are available
- UEFI fallback files: `/EFI/BOOT/BOOTX64.EFI` and `/EFI/BOOT/grub.cfg`

## Non-destructive artifact smoke test

```bash
tests/boot-image-smoke.sh boot-image/hermes-boot.img
```

The smoke test does not mount real devices and does not write to `/dev/sdX`. It:

- verifies image size and MBR/GPT signatures
- reads the FAT partition with mtools at offset `1048576`
- checks for `vmlinuz`, `initramfs.gz`, `auto-deploy.sh`, `syslinux.cfg`
- checks for UEFI fallback files under `/EFI/BOOT/`
- reads `syslinux.cfg` and `grub.cfg` to confirm they boot `/vmlinuz` with `/initramfs.gz`

If the FAT partition offset changes, run with:

```bash
BOOT_IMAGE_OFFSET=<bytes> tests/boot-image-smoke.sh boot-image/hermes-boot.img
```

## Static CI guardrails

CI runs `tests/boot-image-static.sh` to catch regressions that do not require building the image in GitHub Actions, including:

- stale Alpine `vmlinuz-grsec` / `netboot-virt` URLs
- missing LTS netboot kernel/initramfs usage
- missing loop partition rescan
- missing UEFI `BOOTX64.EFI` / `grub.cfg` generation
- missing first-boot native-mode default for the installed service

## What this does not prove

This smoke test proves the image is structurally bootable, not that every target firmware/kernel combination will complete deployment. It does not replace a real hardware boot test, especially on Intel N100/Alder Lake-N machines where the Alpine kernel path has previously been less reliable than the NixOS installer kernel path.
