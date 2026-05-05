# Manual NixOS installer flow

This is the recommended human-auditable install path for Hermes Bootstrap.

Use this when you can boot the target machine into the standard NixOS installer and access this repository from USB, git, or a copied directory.

## 1. Confirm disks

These commands are destructive later. Identify the target disk live; do not use remembered device names.

```bash
lsblk -o NAME,SIZE,MODEL,SERIAL,TRAN,FSTYPE,MOUNTPOINTS
sudo blkid
```

Assumptions below:

- target disk: `/dev/nvme0n1`
- EFI partition: `/dev/nvme0n1p1`
- root partition: `/dev/nvme0n1p2`
- repo path in installer: `/path/to/hermes-bootstrap`

## 2. Partition and format

You can let the deploy script do this after confirmation:

```bash
cd /path/to/hermes-bootstrap
sudo ./scripts/deploy-hermes.sh --partition /dev/nvme0n1
```

Or do it manually if you prefer to inspect every command.

## 3. Bootstrap using nixos-enter + nixos-rebuild

```bash
cd /path/to/hermes-bootstrap
sudo ./scripts/deploy-hermes.sh --bootstrap /dev/nvme0n1 /path/to/hermes-bootstrap
```

The script mounts the target partitions, copies the flake and `deployment-options.nix` to `/mnt/etc/nixos/`, creates a placeholder credential file if needed, and runs the known-good flake path:

```bash
sudo nixos-enter --root /mnt -- /bin/sh -c '
  cd /etc/nixos &&
  nixos-rebuild switch \
    --flake .#hermes \
    --option sandbox false \
    --option accept-flake-config true
'
```

Do not use `nixos-install --flake` for this live-USB flake path. In prior real deployments it failed where `nixos-enter + nixos-rebuild` succeeded.

## 4. First boot checks

After reboot:

```bash
ssh hermes-admin@hermes-node.local
systemctl is-active hermes-agent
journalctl -u hermes-agent -n 100 --no-pager
hermes status
sudo ss -tlnp | grep -E ':22|:8080'
```

## 5. Credentials

If no real env file was provided on the USB, fill in the placeholder:

```bash
sudoedit /var/lib/hermes/secrets/hermes.env
sudo systemctl restart hermes-agent
```

Example:

```bash
MINIMAX_API_KEY=replace-with-real-key
```
