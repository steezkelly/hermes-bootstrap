# hermes-bootstrap Deployment Skill

**Purpose:** Deploy hermes-bootstrap to target hardware via USB
**Context:** Requires manual steps from user at TTY; agent guides via commands

## Prerequisites
- USB stick (Ventoy-preinstalled or raw write)
- Target machine with internal SSD
- Git-cloned hermes-bootstrap on host machine
- NixOS ISO on host machine

## Standard Flow

### Step 1: Prepare USB (on any Linux machine)
```bash
git clone https://github.com/steezkelly/hermes-bootstrap.git
cd hermes-bootstrap
./scripts/setup-hermes-agent.sh --copy ~/.hermes/hermes-agent

# Download NixOS ISO
wget https://channels.nixos.org/nixos-24.05/latest-nixos-minimal-x86_64-linux.iso

# Prepare USB
sudo ./scripts/deploy-hermes.sh --prepare-usb /dev/sdX
```

### Step 2: Boot Target from USB
- Power on → BIOS/UEFI boot menu → select USB
- NixOS minimal installer boots to TTY

### Step 3: Network Setup (if no wired ethernet)
```bash
# Scan WiFi
sudo iw dev wlp1s0 scan | grep SSID

# Configure (replace SSID/PASSWORD)
sudo wpa_passphrase "YourSSID" "YourPassword" | sudo tee /etc/wpa_supplicant.conf
sudo wpa_supplicant -B -i wlp1s0 -c /etc/wpa_supplicant.conf
sudo dhcpcd wlp1s0

# Test
ping -c 3 8.8.8.8
```

### Step 4: Clone bootstrap (if tools not available in live ISO)
```bash
nix-env -i git
git clone https://github.com/steezkelly/hermes-bootstrap ~/
cd ~/hermes-bootstrap
```

### Step 5: Deploy
```bash
sudo bash scripts/deploy-hermes.sh --partition /dev/nvme0n1
sudo bash scripts/deploy-hermes.sh --bootstrap /dev/nvme0n1
```

## Failure Modes

### SquashFS I/O errors (USB hardware degradation)
- Live ISO tools fail (nix-env, curl, git all fail)
- **Fix:** Try different USB port, or boot from PopOS on internal SSD instead
- **Workaround:** In PopOS, clone and prep, then boot target from USB

### WiFi interface name mismatch
- Interface name differs between machines (wlp10s0 vs wlp1s0)
- **Fix:** Always scan first with `ip link show` to find actual name

### Ventoy gray screen / timeout
- Boot process hangs at gray screen
- **Fix:** Try different USB port (USB 2.0 vs 3.0), different brand
- **Workaround:** dd the NixOS ISO directly to USB instead of using Ventoy

### Ethernet direct-connection doesn't work
- Two machines connected directly don't auto-route
- **Fix:** Need a router/switch, or use WiFi

### Network unreachable in NixOS live
- `ping 8.8.8.8` fails
- **Fix:** Use WiFi (wpa_supplicant) — live environment has no NetworkManager

## Important Paths
- hermes-bootstrap: `/mnt/ventoy/hermes-bootstrap/` or `~/hermes-bootstrap/`
- Deploy script: `scripts/deploy-hermes.sh`
- Target SSD: `/dev/nvme0n1`
- USB device: `/dev/sda`

## Ventoy Notes
- Ventoy creates FAT32 partition + exFAT data partition
- ISO files go on exFAT partition (auto-detected at boot)
- Ventoy timeout can be configured in `ventoy.json` on the FAT32 partition
