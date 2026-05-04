# Hermes Bootstrap hardening runbook

This runbook defines the minimum safety checks before using `hermes-bootstrap` on real hardware.

## Threat model

Primary assets:
- Provider credentials in `/var/lib/hermes/secrets/hermes.env`.
- Hermes state in `/var/lib/hermes/.hermes/`.
- Wiki, skills, memory, and working documents under `/var/lib/hermes/`.
- The host NixOS configuration in `/etc/nixos/`.

Primary risks:
- Secret leakage through shell history, logs, screenshots, or committed files.
- Accidental disk destruction during partitioning or USB preparation.
- A bad NixOS rebuild that prevents boot or breaks remote access.
- Exposing the Hermes gateway or SSH beyond the intended local/LAN boundary.
- Losing agent memory/wiki/skills during reinstall or rollback.

Out of scope for this bootstrap repo:
- Hardening every upstream Hermes Agent tool or plugin.
- Protecting against a fully compromised root account.
- Public internet exposure without a separately reviewed reverse proxy and TLS plan.

## Credential handling

Never paste real API keys into commands that are stored in shell history. Prefer an editor with restrictive file permissions:

```bash
sudo install -d -m 0700 -o hermes -g hermes /var/lib/hermes/secrets
sudo install -m 0600 -o hermes -g hermes /dev/null /var/lib/hermes/secrets/hermes.env
sudoedit /var/lib/hermes/secrets/hermes.env
sudo systemctl restart hermes-agent
```

Verify permissions without printing the secret:

```bash
sudo stat -c '%U:%G %a %n' /var/lib/hermes/secrets /var/lib/hermes/secrets/hermes.env
sudo systemctl show hermes-agent -p EnvironmentFiles
```

Expected:
- `/var/lib/hermes/secrets` is owned by `hermes:hermes` and mode `700`.
- `/var/lib/hermes/secrets/hermes.env` is owned by `hermes:hermes` and mode `600`.

## Pre-deploy destructive-action checks

Before running any command that writes a disk:

```bash
lsblk -o NAME,SIZE,MODEL,SERIAL,TRAN,FSTYPE,MOUNTPOINTS
sudo blkid
```

Confirm:
- The USB target is the removable USB device, not the internal SSD.
- The internal install target is the intended NVMe/SATA disk.
- Any valuable data has been backed up.

Do not continue if the device name is inferred from memory. Re-check it live.

## Backup before rebuild or reinstall

Before a risky rebuild or reinstall:

```bash
sudo tar -C /var/lib/hermes -czf /var/lib/hermes-backup-$(date +%Y%m%d-%H%M%S).tgz .hermes wiki skills memory workspace 2>/tmp/hermes-backup-warnings.log
sudo cp -a /etc/nixos /etc/nixos.backup.$(date +%Y%m%d-%H%M%S)
```

If wiki or skills are git repositories, also push them:

```bash
git -C /var/lib/hermes/wiki status --short
git -C /var/lib/hermes/wiki push
git -C /var/lib/hermes/skills status --short
git -C /var/lib/hermes/skills push
```

## Rollback plan

For a bad NixOS rebuild:

```bash
sudo nixos-rebuild list-generations
sudo nixos-rebuild switch --rollback
sudo reboot
```

If the machine cannot boot normally:

```bash
# Boot from installer USB
sudo mount /dev/nvme0n1p2 /mnt
sudo mount /dev/nvme0n1p1 /mnt/boot/efi
sudo nixos-enter
nixos-rebuild list-generations
nixos-rebuild switch --rollback
```

If remote access broke but the machine is otherwise running, use local console and check:

```bash
sudo systemctl status sshd --no-pager
sudo journalctl -u sshd -n 100 --no-pager
ip addr
sudo ss -tlnp
```

## Live verification checks

After install, rebuild, or credential changes:

```bash
systemctl is-active hermes-agent
journalctl -u hermes-agent -n 100 --no-pager
hermes status
hermes tools list
sudo ss -tlnp | grep -E ':22|:8080'
sudo stat -c '%U:%G %a %n' /var/lib/hermes/secrets /var/lib/hermes/secrets/hermes.env
```

Expected network posture:
- SSH is reachable only where intended.
- Hermes gateway binds to `127.0.0.1` unless a reviewed reverse-proxy/TLS plan is in place.

## CI and local validation

Before merging changes:

```bash
tests/shell-syntax.sh
shellcheck --severity=error scripts/*.sh boot-image/*.sh boot-image/overlay/auto-deploy.sh boot-image/overlay/usr/local/bin/hw-detect boot-image/overlay/usr/local/bin/wifi-setup
nix flake metadata ./system/nixos --accept-flake-config
```

The CI workflow runs the same shell and Nix metadata checks on pull requests and pushes to `master`.
