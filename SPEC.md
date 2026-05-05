# hermes-bootstrap v2 — SPEC

**Status:** Implementation
**Created:** 2026-05-01
**Supersedes:** wiki/plans/hermes-bootstrap-v2-iteration.md (planning doc)

---

## What Changed and Why

v1 failed at two points:

1. **Ventoy bootloader** — gray-screen timeout on target hardware. Ventoy's menu is a UEFI app that doesn't run reliably on all BIOS/UEFI implementations.
2. **NixOS live environment** — SquashFS I/O errors on target hardware. The live environment reads compressed data from USB at high throughput; cheap USB drives and USB 2.0 ports can't sustain it.

**v2 removes both failure points.** No Ventoy. No SquashFS. Instead, a minimal Alpine-based boot environment boots directly (no intermediate bootloader menu), reads files from a plain FAT32/exFAT USB partition, and runs the NixOS installer from there.

---

## Boot Flow

```
HOST MACHINE (Linux Mint, any desktop)
│
├── Step 1: Build boot image
│   cd hermes-bootstrap/boot-image/
│   sudo ./make-boot-image.sh          ← builds hermes-boot.img (~80MB)
│
├── Step 2: Write USB
│   sudo dd if=hermes-boot.img of=/dev/sdX bs=4M status=progress conv=fsync
│   ← single-step. No Ventoy. No partition magic.
│
└── USB is now a self-contained boot stick
    (FAT32 partition, ~80MB boot image + hermes-bootstrap data)

TARGET MACHINE (Minipc, bare metal)
│
├── Step 3: Boot from USB
│   BIOS/UEFI → select USB → direct boot into Alpine initrd
│   ↓ (no bootloader menu, no Ventoy, no gray screen)
│
├── Step 4: Auto-deploy (runs in Alpine initrd)
│   /auto-deploy.sh
│   ├── detect hardware  → echo what was found
│   ├── bring up network → WiFi guided setup (or ethernet DHCP)
│   ├── partition SSD    → EFI + root on target
│   ├── mount USB data   → hermes-bootstrap/ + NixOS ISO
│   ├── install system   → nixos-enter + nixos-rebuild from target root
│   └── reboot
│
└── Step 5: NixOS on internal SSD
    hermes-node boots. hermes-agent.service running.
    Agent has full root ownership.
```

---

## USB Layout

```
/dev/sdX (whole USB)
│
└── /dev/sdX1  FAT32  "HERMES-BOOT"  (entire drive, or remaining after boot image)
    │
    ├── hermes-bootstrap/         ← the repo (git clone)
    │   ├── scripts/
    │   │   ├── deploy-hermes.sh
    │   │   └── setup-hermes-agent.sh
    │   ├── system/nixos/          ← flake + hermes-agent-src
    │   │   ├── flake.nix
    │   │   └── hermes-agent-src/  ← pre-bundled agent source
    │   ├── data/
    │   │   ├── skills/
    │   │   ├── wiki/
    │   │   └── secrets/           ← hermes.env (user fills in)
    │   └── docs/
    │
    └── NixOS-24.05-minimal.iso   ← installer (plain file copy)
```

The NixOS ISO is a **plain file** on the FAT32 partition — no Ventoy, no ISO booting complexity. The Alpine boot environment loops-mounts it inside the initrd to run the installer.

---

## Boot Image: hermes-boot.img

Built by `boot-image/make-boot-image.sh`. ~80MB. Contains:

- **Alpine Linux mini root filesystem** (apkovl overlay)
- **Busybox** (ash, sh, ls, cp, mv, mkdir, cat, grep, etc.)
- **network scripts** (wpa_supplicant, dhcpcd, iw)
- **parted + mkfs** (partition and format tools)
- **nix-installer binary** (extracted from the NixOS ISO)
- **auto-deploy.sh** (orchestrates the whole deployment)
- **hermes-bootstrap/** (symlinked or copied from USB data partition at boot)

**What it does NOT contain:** NixOS itself. That comes from the ISO on the USB.

### Build Requirements (for make-boot-image.sh)
- Docker (Alpine container to build the initrd)
- Or: apk, mkinitfs, dosfstools on Alpine/Linux
- Builds on Linux Mint, Pop!_OS, any Linux

---

## auto-deploy.sh — Deployment Orchestrator

Runs inside the Alpine boot environment (not NixOS). Steps:

### 1. Hardware Detection
```
echo "=== Hardware Detection ==="
lsblk -o NAME,SIZE,TYPE,TRAN,MODEL
ip link show
iw dev list
nix --version 2>/dev/null || echo "Nix not in initrd (expected)"
echo "NixOS ISO: $(ls /mnt/usb/NixOS*.iso 2>/dev/null || echo 'NOT FOUND')"
```

### 2. Network Bring-Up
```
# Try ethernet DHCP first
dhcpcd || true

# If no ethernet, try WiFi auto-connect (saved networks in /etc/wpa_supplicant.conf)
wpa_supplicant -B -i wlan0 -c /etc/wpa_supplicant.conf 2>/dev/null || {
  # Fallback: guided WiFi setup
  echo "No ethernet. Scanning WiFi..."
  iw dev wlan0 scan | grep SSID
  read -p "SSID: " SSID
  read -sp "Password: " PASSWORD
  wpa_passphrase "$SSID" "$PASSWORD" | tee /etc/wpa_supplicant.conf
  wpa_supplicant -B -i wlan0 -c /etc/wpa_supplicant.conf
}
dhcpcd
ping -c 1 8.8.8.8
```

### 3. Partition Target SSD
```
# Warn + confirm
echo "WARNING: ALL DATA ON $TARGET_SSD WILL BE DESTROYED"
lsblk "$TARGET_SSD"
read -p "Type 'yes' to confirm: " CONFIRM
[[ "$CONFIRM" = "yes" ]] || exit 1

# Partition: EFI (512MB) + root (rest)
parted -s "$TARGET_SSD" mklabel gpt
parted -s "$TARGET_SSD" mkpart primary fat32 512MB 1024MB
parted -s "$TARGET_SSD" set 1 esp on
parted -s "$TARGET_SSD" name 1 EFI
parted -s "$TARGET_SSD" mkpart primary ext4 1024MB 100%
parted -s "$TARGET_SSD" name 2 HERMES

mkfs.fat -F 32 -n EFI "${TARGET_SSD}1"
mkfs.ext4 -L HERMES -E lazy_itable_init "${TARGET_SSD}2"
```

### 4. Install from inside the target root
Mount the target partitions, copy the flake into `/mnt/etc/nixos`, then build from inside the target root. Do **not** use `nixos-install --flake` for the flake path; it has failed in live USB contexts. The reliable path is:
```
nixos-enter --root /mnt -- /bin/sh -c '
  cd /etc/nixos &&
  nixos-rebuild switch \
    --flake .#hermes \
    --option sandbox false \
    --option accept-flake-config true
'
```

The deploy scripts create `/mnt/etc/nixos/flake.nix`, seed `/mnt/var/lib/hermes/secrets/hermes.env`, and then run this command.
### 5. Reboot
```
umount -R /mnt
reboot
```

---

## Changes to deploy-hermes.sh (v1 → v2)

The `--prepare-usb` step changes fundamentally:

**v1:**
```
1. Create Ventoy partitions
2. Install Ventoy bootloader
3. Copy hermes-bootstrap + ISO to Ventoy USB
```

**v2:**
```
1. Create single FAT32 partition on USB
2. Copy hermes-bootstrap/ + NixOS ISO to it
3. Write hermes-boot.img to a second partition OR embed it at start of USB
```

Simpler: **two USB drives** — one boot stick (hermes-boot.img), one data stick (hermes-bootstrap + ISO). Eliminates the partition juggling entirely.

Or: **single USB with two partitions** — partition 1: hermes-boot.img (bootable), partition 2: FAT32 data.

### Specific Changes

| Location | Change |
|---|---|
| `prepare_usb()` | Remove Ventoy. Create FAT32. Copy files. Done. |
| `bootstrap_nixos()` | Add WiFi config, copy flake into target, run nixos-enter + nixos-rebuild from target root. |
| New: `wifi_setup()` | Guided WiFi setup with scan + wpa_passphrase |
| New: `usb_io_retry()` | Wrap USB mount with 3x retry + different mount options |
| New: `hardware_detect()` | Echo lsblk, ip link, iw dev at start of each step |
| `--all` flow | Changes to: build-image → write-usb → auto-deploy (no user TTY steps) |

---

## Failure Handling

| Failure | Detection | Recovery |
|---|---|---|
| USB I/O error on read | `cp` or `mount` fails with EIO | Retry 3x, then try different USB port or mount -o sync |
| WiFi not reachable | `ping -c 1 8.8.8.8` fails | Fallback to guided WiFi setup |
| Ethernet no DHCP | `dhcpcd eth0` times out | Try WiFi |
| flake rebuild fails | non-zero exit from `nixos-rebuild switch` | Show command output; re-enter with `nixos-enter --root /mnt` and inspect `/etc/nixos` |
| Wrong device selected | confirm() prompt | Must type "yes" to proceed |
| NixOS ISO missing on USB | file not found | Error with instructions to copy it |
| Ventoy fallback needed | user chooses alternative | ventoy.json timeout=5 workaround |

---

## Non-Goals (What's NOT Changing)

- The NixOS flake (`system/nixos/flake.nix`) stays the same
- hermes-agent NixOS module integration stays the same
- The hermes-agent service setup on the target stays the same
- `/var/lib/hermes` structure and git-tracking stays the same
- The self-modification loop (`nixos-rebuild switch`) stays the same

v2 only changes: **how the USB boots** and **how the installer gets network**. The target NixOS system is identical.

---

## File Inventory

```
hermes-bootstrap/
├── SPEC.md                           ← THIS FILE
├── README.md                          ← updated for v2 flow
├── scripts/
│   ├── deploy-hermes.sh               ← v2: WiFi + retry + hardware echo
│   └── setup-hermes-agent.sh          ← v2: always run before prepare-usb
├── boot-image/                        ← NEW: Alpine boot environment
│   ├── make-boot-image.sh             ← builds hermes-boot.img
│   ├── Dockerfile                     ← build container (Alpine-based)
│   ├── overlay/                       ← files injected into initrd
│   │   ├── etc/
│   │   │   ├── wpa_supplicant.conf
│   │   │   └── network/interfaces
│   │   ├── auto-deploy.sh             ← main orchestrator
│   │   └── usr/
│   │       └── local/
│   │           └── bin/
│   │               ├── hw-detect
│   │               ├── wifi-setup
│   │               └── partition-ssd
│   └── hermes-boot.img                ← built artifact (gitignored)
├── system/nixos/
│   └── (unchanged)
└── data/
    └── (unchanged)
```

---

## Build Instructions (v2 USB Creation)

```bash
# On any Linux machine
git clone https://github.com/steezkelly/hermes-bootstrap.git
cd hermes-bootstrap

# Bundle hermes-agent source (REQUIRED)
./scripts/setup-hermes-agent.sh --copy ~/.hermes/hermes-agent

# Build the boot image (~5 min first time, Docker pulls Alpine)
cd boot-image/
sudo ./make-boot-image.sh            # → hermes-boot.img
cd ..

# Copy NixOS ISO onto the data partition
wget https://channels.nixos.org/nixos-24.05/latest-nixos-minimal-x86_64-linux.iso

# Write USB (two partitions: boot image + data)
sudo dd if=boot-image/hermes-boot.img of=/dev/sdX bs=4M status=progress
# Then: create FAT32 on remaining space, copy hermes-bootstrap/ + ISO to it

# DONE. Boot target from USB.
```

---

## Glossary

| Term | Meaning |
|---|---|
| hermes-boot.img | Alpine-based bootable image written directly to USB via dd |
| Auto-deploy | Shell script that runs inside Alpine boot env, orchestrates entire deployment |
| hermes-bootstrap | The git repo containing flake, scripts, and data |
| NixOS ISO | Standard NixOS minimal installer — treated as a plain file on the USB data partition |
| Target SSD | Internal storage (nvme or SATA) where NixOS gets installed |
| Ventoy | Previous approach — removed in v2 |
