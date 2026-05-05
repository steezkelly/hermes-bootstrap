# NixOS configuration

This directory contains the NixOS flake used by Hermes Bootstrap.

## What it defines

`flake.nix` builds a `nixosConfigurations.hermes` system with:

- NixOS 24.05 for `x86_64-linux`
- `NousResearch/hermes-agent` as a flake input
- `services.hermes-agent.enable = true`
- Hermes Agent state in `/var/lib/hermes`
- Docker-backed container mode for agent tool execution
- provider credentials loaded from `/var/lib/hermes/secrets/hermes.env`
- SSH enabled with root login disabled
- Hermes gateway bound to `127.0.0.1` by default
- an interactive admin user named `hermes-admin`

## Validate

From the repository root:

```bash
nix flake metadata ./system/nixos --accept-flake-config
```

On a NixOS host, a fuller build check is:

```bash
sudo nixos-rebuild build --flake ./system/nixos#hermes --show-trace
```

## Install flow

The safer public flow is to use the repository-level deploy script from a NixOS installer environment:

```bash
cd /path/to/hermes-bootstrap
sudo ./scripts/deploy-hermes.sh --partition /dev/nvme0n1
sudo ./scripts/deploy-hermes.sh --bootstrap /dev/nvme0n1 /path/to/hermes-bootstrap
```

Internally, the bootstrap step copies `flake.nix` into `/mnt/etc/nixos`, seeds `/mnt/var/lib/hermes/secrets/hermes.env`, then runs:

```bash
sudo nixos-enter --root /mnt -- /bin/sh -c '
  cd /etc/nixos &&
  nixos-rebuild switch \
    --flake .#hermes \
    --option sandbox false \
    --option accept-flake-config true
'
```

Avoid `nixos-install --flake` for this flake-based live-USB flow; it has failed in installer environments where `nixos-enter + nixos-rebuild` succeeds.

The `--partition` step destroys the target disk after confirmation. Re-check device names with `lsblk` immediately before running it.

## Credentials

Do not put real provider keys in Nix files. The service reads:

```text
/var/lib/hermes/secrets/hermes.env
```

Create it on the installed system with restrictive permissions:

```bash
sudo install -d -m 0700 -o hermes -g hermes /var/lib/hermes/secrets
sudo install -m 0600 -o hermes -g hermes /dev/null /var/lib/hermes/secrets/hermes.env
sudoedit /var/lib/hermes/secrets/hermes.env
sudo systemctl restart hermes-agent
```

Example content:

```bash
MINIMAX_API_KEY=replace-with-real-key
```

## First boot checks

```bash
ssh hermes-admin@hermes-node.local
systemctl is-active hermes-agent
journalctl -u hermes-agent -n 100 --no-pager
hermes status
sudo ss -tlnp | grep -E ':22|:8080'
```

## Known limitations

- Hardware configuration is still partly template-driven and should be reviewed after `nixos-generate-config`.
- Hostname, provider/model, and admin username are currently defaults in `flake.nix`; they should become explicit deployment parameters.
- The repo contains both manual-installer and experimental boot-image workflows. Prefer the manual path until you have reviewed the hardware notes in `SPEC.md`.
