# NixOS configuration

This directory contains the NixOS flake used by Hermes Bootstrap.

## What it defines

`flake.nix` builds a `nixosConfigurations.hermes` system with:

- NixOS 24.05 for `x86_64-linux`
- `NousResearch/hermes-agent` as a flake input
- `services.hermes-agent.enable = true`
- Hermes Agent state in `/var/lib/hermes`
- Native first boot for `hermes-agent.service` by default, with optional Docker-backed container mode for agent tool execution
- provider/model, gateway bind, admin user, hostname, locale, secrets path, and runtime mode loaded from `deployment-options.nix`
- SSH enabled with root login disabled
- Hermes gateway bound to `127.0.0.1` by default
- an interactive admin user named `hermes-admin`

## Deployment options

Edit `deployment-options.nix` before deployment to change the reusable defaults without touching the main flake:

```nix
{
  hostName = "hermes-node";
  adminUser = "hermes-admin";
  provider = "minimax";
  model = "minimax/minimax-m2.7";
  containerMode = false;
  gatewayHost = "127.0.0.1";
  gatewayPort = 8080;
}
```

Keep `gatewayHost = "127.0.0.1"` unless you have a reviewed reverse-proxy/TLS/auth plan.

Keep `containerMode = false` for network-independent first boot. Setting it to `true` enables upstream Docker-backed container mode, but first service start can need Docker image pulls plus in-container apt, NodeSource, Astral uv, and uv Python downloads. See `../../docs/first-boot-network.md`.

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

Internally, the bootstrap step copies `flake.nix`, `deployment-options.nix`, `agent-extra-packages.nix`, and optional `flake.lock` into `/mnt/etc/nixos`, preserves generated hardware configuration when available, seeds `/mnt/var/lib/hermes/secrets/hermes.env`, then runs:

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

- Generated hardware configuration is preserved when available; fallback hardware configuration is intentionally minimal and should be reviewed after first boot.
- Deployment defaults are centralized in `deployment-options.nix`; edit that file before deployment to change host/user/provider/gateway values.
- The repo contains both manual-installer and experimental boot-image workflows. Prefer the manual path until you have reviewed the hardware notes in `SPEC.md`.
