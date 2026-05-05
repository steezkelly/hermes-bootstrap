# hermes-bootstrap deployment notes

Purpose: deploy Hermes Bootstrap to target hardware via USB or a standard NixOS installer environment.

This file is historical/operator-focused. The recommended public walkthrough is `docs/install-manual-nixos.md`.

## Prerequisites

- USB stick or other way to get this repository into the NixOS installer
- target x86_64 machine with an internal disk that may be erased
- NixOS minimal ISO
- live disk verification with `lsblk` before destructive operations

## Recommended flow

### 1. Prepare and review on an admin machine

```bash
git clone https://github.com/steezkelly/hermes-bootstrap.git
cd hermes-bootstrap

# Optional: bundle a local hermes-agent checkout for local-source/offline experiments.
./scripts/setup-hermes-agent.sh --copy /path/to/hermes-agent

# Optional validation.
tests/shell-syntax.sh
nix flake metadata ./system/nixos --accept-flake-config
```

### 2. Boot target into the NixOS installer

- Power on → BIOS/UEFI boot menu → select USB
- NixOS minimal installer boots to TTY
- Bring up network if needed

WiFi interface names vary. Discover them live:

```bash
ip link show
iw dev
```

### 3. Deploy

```bash
cd /path/to/hermes-bootstrap
sudo bash scripts/deploy-hermes.sh --partition /dev/nvme0n1
sudo bash scripts/deploy-hermes.sh --bootstrap /dev/nvme0n1 /path/to/hermes-bootstrap
```

The bootstrap step uses the reliable flake path:

```bash
sudo nixos-enter --root /mnt -- /bin/sh -c '
  cd /etc/nixos &&
  nixos-rebuild switch \
    --flake .#hermes \
    --option sandbox false \
    --option accept-flake-config true
'
```

Do not use `nixos-install --flake` for this live-USB flake deployment path; it has failed in prior real deployments where `nixos-enter + nixos-rebuild` worked.

## Failure modes

### SquashFS I/O errors

- Live ISO tools fail during sustained USB reads.
- Try another USB port/stick, or use a different boot path.

### WiFi interface name mismatch

- Interface name differs between machines.
- Always inspect with `ip link show` and `iw dev`.

### Ventoy gray screen / timeout

- Boot process hangs at a gray screen.
- Try another USB port/stick, raw NixOS ISO write, or the documented boot-image path.

### Network unreachable in NixOS live

- `ping 8.8.8.8` fails.
- Use `wpa_supplicant`/DHCP manually; the minimal live environment has no NetworkManager.

## Important paths

- repo in installer: `/path/to/hermes-bootstrap`
- deploy script: `scripts/deploy-hermes.sh`
- target disk example: `/dev/nvme0n1`
- target flake after copy: `/mnt/etc/nixos/flake.nix`
- target secrets placeholder: `/mnt/var/lib/hermes/secrets/hermes.env`
