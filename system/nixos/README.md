# HERMES OS — Self-Owned AI Environment

## What Is This?

A complete, reproducible NixOS installation for hermes-agent.
Boot from USB → installer → internal SSD → AI agent running.
No assumptions, no implicit state, fully declarative.

---

## Hardware Layout

```
USB STICK (226GB, Ventoy bootloader)
├── Partition 1: FAT32, LABEL=VENTOY
│   └── Ventoy bootloader + NixOS ISO
└── (removed after install)

INTERNAL SSD (512GB, target system)
├── /dev/nvme0n1p1: EFI System Partition  512MB  FAT32  (/boot/efi)
├── /dev/nvme0n1p2: Linux filesystem     ~495GB  ext4   (/)
└── /dev/nvme0n1p3: (optional swap)      16GB   swap
```

---

## Build the USB Boot Stick

### 1. Partition the USB

```bash
# Find your USB device (CRITICAL — wrong device = data loss)
lsblk
# Look for a 226GB device with a similar model name

sudo parted /dev/sdX -- mklabel gpt
sudo parted /dev/sdX -- mkpart primary fat32 0% 8GB
sudo parted /dev/sdX -- name 1 VENTOY
sudo mkfs.fat -F 32 -n VENTOY /dev/sdX1
```

### 2. Install Ventoy

```bash
# Download latest Ventoy
wget https://github.com/Ventoy/Ventoy/releases/latest/ventoy-*.xz
unxz ventoy-*.xz

# Install Ventoy (only touches the VENTOY partition, preserves others)
sudo ./Ventoy2Disk.sh -i /dev/sdX -g

# Verify
lsblk /dev/sdX
# Should show: 8GB VENTOY partition
```

### 3. Copy the NixOS ISO to USB

```bash
# Download NixOS 24.05 minimal ISO
wget https://channels.nixos.org/nixos-24.05/latest-nixos-minimal-x86_64-linux.iso
mv nixos-*.iso /path/to/mounted/ventoy/NixOS-24.05-minimal.iso
```

### 4. Copy the hermes-bootstrap to USB

```bash
# Copy the entire bootstrap directory
cp -r /path/to/hermes-bootstrap /path/to/mounted/ventoy/hermes-bootstrap
sync
```

---

## Install NixOS to Internal SSD

### 1. Boot from USB

- Insert USB
- Power on → BIOS/UEFI boot menu → select USB
- Ventoy menu appears → select NixOS ISO
- NixOS minimal installer boots to TTY

### 2. Partition Internal SSD

```bash
# Identify internal SSD (NOT the USB)
lsblk
# Look for ~512GB device (nvme0n1 or sda, depends on hardware)

sudo parted /dev/nvme0n1 -- mklabel gpt
sudo parted /dev/nvme0n1 -- mkpart primary fat32 512MB
sudo parted /dev/nvme0n1 -- set 1 esp on
sudo parted /dev/nvme0n1 -- mkpart primary ext4 512MB 100%
sudo parted /dev/nvme0n1 -- name 1 EFI
sudo parted /dev/nvme0n1 -- name 2 HERMES

# Format
sudo mkfs.fat -F 32 -n EFI /dev/nvme0n1p1
sudo mkfs.ext4 -L HERMES -E lazy_itable_init /dev/nvme0n1p2
```

### 3. Install NixOS

```bash
# Mount target
sudo mount /dev/nvme0n1p2 /mnt
sudo mkdir -p /mnt/boot/efi
sudo mount /dev/nvme0n1p1 /mnt/boot/efi

# Generate hardware config
sudo nixos-generate-config --root /mnt

# Copy hermes configuration
sudo cp hermes-bootstrap/system/nixos/* /mnt/etc/nixos/
sudo mv /mnt/etc/nixos/configuration.nix /mnt/etc/nixos/configuration.nix.bak
sudo cat > /mnt/etc/nixos/configuration.nix << 'EOF'
# HERMES OS — see hermes-bootstrap/system/nixos/ for source
(import /mnt/etc/nixos/hermes-module.nix) {
  pkgs = import <nixpkgs> {};
  imports = [ ];
  # Hardware auto-detected, augment below
}
EOF

# Install (this takes a while)
sudo nixos-install --no-root-password

# Set root password (do this before reboot)
sudo chroot /mnt passwd

# Unmount and reboot
sudo umount -R /mnt
sudo reboot
```

### 4. Post-Install: Restore Hermes Data

```bash
# SSH in as steve, then sudo
ssh steve@hermes-node.local
sudo -i

# Check hermes-agent status
systemctl status hermes-agent
hermes-agent --version

# Restore wiki
cd /var/lib/hermes
sudo -u hermes git clone https://github.com/YOUR/wiki-backup.git wiki

# Restore skills
sudo -u hermes git clone https://github.com/YOUR/skills-backup.git skills

# Restart agent
systemctl restart hermes-agent
```

---

## Configuration Source

All configuration lives in `hermes-bootstrap/system/nixos/`:

```
system/nixos/
├── hermes-module.nix    ← The full NixOS module (imports hermes-agent flake)
├── flake.nix            ← Flake referencing real hermes-agent + hermes-agent
├── flake.lock           ← Locked inputs
└── README.md            ← This file
```

To update the system after changes:
```bash
cd /etc/nixos
sudo git pull
sudo nixos-rebuild switch
```

---

## What Running Looks Like

```
hermes-node systemd[1]: Started hermes-agent.service - Hermes Agent Gateway.
hermes-agent[1234]: === HERMES GATEWAY ONLINE ===
hermes-agent[1234]: Version: 2.1.4
hermes-agent[1234]: Provider: nous / minimax/minimax-m2.7
hermes-agent[1234]: State: /var/lib/hermes/.hermes
hermes-agent[1234]: Config: /var/lib/hermes/.hermes/config.yaml (managed)
hermes-agent[1234]: Plugins: 12 loaded
hermes-agent[1234]: MCP servers: 3 configured
hermes-agent[1234]: ========================================
```

---

## Recovery

### Can't boot?
- `journalctl -b -1` — previous boot logs
- Check EFI partition: `mount /dev/nvme0n1p1 /mnt && ls /mnt/EFI/`
- Re-run installer: boot from USB → `sudo nixos-enter`

### hermes-agent won't start?
```bash
journalctl -u hermes-agent -n 100
hermes-agent gateway --doctor
```

### NixOS rebuild fails?
```bash
sudo nixos-rebuild switch --show-trace --verbose
```

### Full system recovery from USB
```bash
# Boot from USB → NixOS installer TTY
sudo cryptsetup open /dev/nvme0n1p2 hermes
sudo mount /dev/mapper/hermes /mnt
sudo mount /dev/nvme0n1p1 /mnt/boot/efi
sudo nixos-enter
# Now you're in the broken system, can fix /etc/nixos
```
