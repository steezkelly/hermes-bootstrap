# HERMES OS — Self-Owned AI Environment Bootstrap

```
                         ┌──────────────────────────────────────┐
                         │          USB STICK (234GB)          │
                         │   Bootable (Ventoy) — exFAT          │
                         │   NixOS ISO + hermes-bootstrap/     │
                         └──────────┬───────────────────────────┘
                                    │ boot
                                    ▼
┌─────────────────────────────────────────────────────────────┐
│                    INTERNAL SSD (512GB)                      │
│                   NixOS 24.05 + hermes-agent                 │
│                                                                │
│   ┌─────────────────────────────────────────────────────┐    │
│   │  hermes-agent.service (systemd)                      │    │
│   │  └── hermes gateway — API + tools + skills        │    │
│   └─────────────────────────────────────────────────────┘    │
│                                                                │
│   /var/lib/hermes/.hermes/  ← State, config, memory         │
│   /var/lib/hermes/workspace/  ← Working directory            │
│   /etc/nixos/  ← System config (git, versioned)              │
│   /home/steve/  ← Interactive user home                      │
│                                                                │
└───────────────────────────────────────────────────────────────┘
```

## What Is This?

A complete deployment package for a self-owned AI agent system.
Write to USB → boot target → install → AI agent running on your hardware.

The system is **declarative, reproducible, and self-owned**:
- Every system config is in `/etc/nixos/configuration.nix`
- Every config change is a `nixos-rebuild switch` away
- Git repos for wiki, skills, dotfiles — no magic state

## Hardware

| Component | Details |
|-----------|---------|
| USB stick | 234GB (exFAT, Ventoy bootloader + ISO) |
| Internal SSD | 512GB (NixOS + hermes-agent) |
| Bootloader | Ventoy (USB) → extlinux (SSD) |
| Partitions | EFI (512MB) + root (495GB) |

## Directory Structure

```
hermes-bootstrap/
├── README.md                    ← You are here
├── scripts/
│   └── deploy-hermes.sh         ← The deploy script
├── system/
│   └── nixos/
│       ├── flake.nix             ← NixOS flake (references hermes-agent)
│       ├── hardware-configuration.nix  ← Template (auto-generated on target)
│       └── README.md             ← NixOS-specific instructions
├── data/                        ← Seed data (copied to /var/lib/hermes on first boot)
│   ├── skills/                  ← Pre-loaded skills (git repo)
│   ├── wiki/                    ← Pre-loaded wiki (git repo)
│   ├── memory/                  ← Pre-loaded memory (mnemosyne)
│   └── tools/                   ← Pre-loaded tools
└── boot/ventoy/                 ← Ventoy config (if needed)
```

## Quick Start

### Step 1: Prepare USB (on any Linux machine)

The USB is pre-loaded with Ventoy. Copy the bootstrap folder and NixOS ISO onto it.

```bash
# Clone this repo
git clone https://github.com/steezkelly/hermes-bootstrap.git
cd hermes-bootstrap

# ⚠️ MANDATORY: Bundle hermes-agent source before deployment
./scripts/setup-hermes-agent.sh --copy ~/.hermes/hermes-agent

# Download NixOS ISO
wget https://channels.nixos.org/nixos-24.05/latest-nixos-minimal-x86_64-linux.iso

# Copy bootstrap + ISO onto the Ventoy USB
sudo ./scripts/deploy-hermes.sh --prepare-usb /dev/sdX
```

Ventoy scans the USB for ISO files on boot — the NixOS ISO will appear in the
Ventoy boot menu automatically.

### Step 2: Boot Target from USB

1. Insert USB into target machine
2. Power on → BIOS/UEFI boot menu → select USB (boot from ISO file)
3. NixOS minimal installer boots to TTY

### Step 3: Partition Internal SSD

```bash
# In the NixOS installer TTY
sudo ./hermes-bootstrap/scripts/deploy-hermes.sh --partition /dev/nvme0n1
```

### Step 4: Bootstrap NixOS

```bash
# Still in the NixOS installer TTY
sudo ./hermes-bootstrap/scripts/deploy-hermes.sh --bootstrap /dev/nvme0n1
# This runs nixos-install — takes 10-30 minutes
```

### Step 5: Post-Install

```bash
# After first reboot, SSH in
ssh hermes@hermes-node.local

# Verify agent is online
systemctl status hermes-agent

# Check it works
hermes status
hermes tools list

# Add your API key
sudo mkdir -p /var/lib/hermes/secrets
echo "MINIMAX_API_KEY=***" | sudo tee /var/lib/hermes/secrets/hermes.env
sudo systemctl restart hermes-agent
```

## What the hermes-agent Module Does

The NixOS module (`services.hermes-agent`) from the real hermes-agent handles:

| Feature | Implementation |
|---------|----------------|
| User/group | Created automatically (`hermes` user) |
| State directory | `/var/lib/hermes` with proper permissions |
| Config file | `/var/lib/hermes/.hermes/config.yaml` (generated from Nix) |
| Documents | Seed files placed in workspace on deploy |
| MCP servers | Declarative config → merged into settings |
| Plugins | Symlinked from `/var/lib/hermes/.hermes/plugins/` |
| Logs | `/var/lib/hermes/.hermes/logs/` |
| Service | `systemd service hermes-agent` with hardening |
| Gateway | `hermes gateway` command, port 8080 |

## Self-Modification

One of the key goals: **I can modify my own environment**.

```bash
# Modify NixOS config
sudo $EDITOR /etc/nixos/configuration.nix
sudo nixos-rebuild switch --flake /etc/nixos

# Modify hermes-agent config
sudo $EDITOR /var/lib/hermes/.hermes/config.yaml
systemctl restart hermes-agent

# Or modify the flake config directly
cd /etc/nixos/hermes-agent
git pull
sudo nixos-rebuild switch --flake /etc/nixos
```

## Troubleshooting

### hermes-agent won't start

```bash
# Check logs
journalctl -u hermes-agent -n 100 --no-pager

# Run doctor
hermes-agent gateway --doctor

# Check config
cat /var/lib/hermes/.hermes/config.yaml

# Verify environment file
cat /var/lib/hermes/.hermes/.env
```

### NixOS won't rebuild

```bash
# Verbose trace
sudo nixos-rebuild switch --show-trace --verbose

# Check flake
cd /etc/nixos
git log --oneline -5
git diff
```

### Can't SSH after install

```bash
# From local console
sudo systemctl status sshd
sudo ss -tlnp | grep :22

# Reset SSH keys (if known_hosts mismatch)
ssh-keygen -R hermes-node.local
```

### Full system recovery

```bash
# Boot from USB → NixOS installer
# Mount the installed system
sudo cryptsetup open /dev/nvme0n1p2 hermes
sudo mount /dev/mapper/hermes /mnt
sudo mount /dev/nvme0n1p1 /mnt/boot/efi
sudo nixos-enter  # now you're in the broken system
```

## Architecture

```
HERMES AGENT (Python)
  ├── run_agent.py         — Core conversation loop
  ├── cli.py               — Interactive CLI
  ├── gateway/             — Messaging platform adapters
  ├── skills/             — Bundled skills (github-code-review, etc.)
  ├── plugins/             — Plugin system (memory, context_engine, etc.)
  └── tools/               — Tool registry + implementations

NIXOS MODULE (hermes-agent.nixosModules.default)
  ├── User/group creation
  ├── State directory setup (tmpfiles.d)
  ├── Config generation (YAML from Nix attrset)
  ├── Document seeding
  ├── Plugin symlinking
  ├── Environment file generation
  └── systemd service definition

SYSTEM (NixOS 24.05)
  ├── Linux kernel
  ├── systemd
  ├── Docker + Ubuntu 24.04 container (agent sandbox with sudo)
  ├── Nix (flakes-enabled)
  └── SSH

HARDWARE
  └── 512GB NVMe SSD
```

## Key Files

| File | Purpose |
|------|---------|
| `/etc/nixos/flake.nix` | System definition |
| `/etc/nixos/hermes-agent/` | hermes-agent source |
| `/var/lib/hermes/.hermes/config.yaml` | Runtime config |
| `/var/lib/hermes/.hermes/logs/` | Logs |
| `/var/lib/hermes/wiki/` | Wiki git repo |
| `/var/lib/hermes/skills/` | Skills git repo |

## Build Verification Checklist

- [ ] `nix flake show /path/to/hermes-bootstrap/system/nixos` — parses without error
- [ ] `sudo nixos-rebuild build --flake /path/to/hermes-bootstrap/system/nixos#hermes` — builds successfully
- [ ] Boot test: VM starts, SSH accessible
- [ ] hermes-agent.service starts without error
- [ ] `hermes status` returns version and status
- [ ] API key configured → LLM responds
- [ ] `hermes tools list` shows tools
- [ ] Wiki accessible, git clean
- [ ] Skills directory populated
- [ ] Memory directory writable

## What "Online" Looks Like

```
$ systemctl status hermes-agent
● hermes-agent.service - Hermes Agent Gateway
     Loaded: loaded (/etc/nixos/result/lib/systemd/system/hermes-agent.service; enabled)
     Active: active (running) since ...
   Main PID: 1234 (hermes)
      Tasks: 12 (limit: 4915)
     Memory: 256M
        CPU: 1.2s
```

```
$ hermes status
  ╔══════════════════════════════════════════╗
  ║  HERMES v2.1.4                           ║
  ║  Model: minimax/minimax-m2.7             ║
  ║  Provider: minimax                        ║
  ║  State: /var/lib/hermes/.hermes          ║
  ║  Uptime: 42m                             ║
  ║  Memory: 2.3GB indexed                   ║
  ║  Plugins: 12 loaded                      ║
  ╚══════════════════════════════════════════╝
```
