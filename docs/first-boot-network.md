# First-boot network dependency

This note traces the installed `hermes-agent` service startup path and the network dependencies that existed when the service defaulted to upstream OCI container mode.

## Trace

`system/nixos/flake.nix` imports the upstream Hermes Agent NixOS module:

```nix
hermes-agent.nixosModules.default
```

The pinned upstream input is recorded in `system/nixos/flake.lock`. At the time this note was written, the relevant upstream module was:

```text
NousResearch/hermes-agent d12f59aa5377635f7f4ad680cc349bf3e770a5d8
nix/nixosModules.nix
```

When `services.hermes-agent.container.enable = true`, upstream replaces the native service with a Docker-backed persistent container service. Its `preStart` creates a container named `hermes-agent` using the configured image. If the image is not present locally, Docker pulls it during service start.

The previous repo default was:

```nix
container.enable = true;
container.backend = "docker";
container.image = "ubuntu:24.04";
```

That made first service start depend on Docker registry access for `ubuntu:24.04` unless the image was already cached.

Inside the container, upstream's generated entrypoint performs first-boot provisioning. The relevant operations are:

- `apt-get update`
- `apt-get install sudo curl ca-certificates gnupg`
- fetch NodeSource signing key from `https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key`
- add the NodeSource `node_22.x` apt source
- `apt-get update`
- `apt-get install nodejs`
- install uv via `curl -LsSf https://astral.sh/uv/install.sh | sh`
- `uv python install 3.12`
- `uv venv --python 3.12 --seed "$HOME/.venv"`

So a successful NixOS install could still leave `hermes-agent.service` blocked or restart-looping on first boot unless the installed machine could reach Docker Hub/a registry mirror, Ubuntu apt mirrors, NodeSource, Astral, and uv's Python distribution source.

## Implemented hardening

`deployment-options.nix` now makes runtime mode explicit:

```nix
containerMode = false;
containerBackend = "docker";
containerImage = "ubuntu:24.04";
```

`flake.nix` wires those options into `services.hermes-agent` and sets:

```nix
addToSystemPackages = true;
```

The default is now native first boot. In native mode, the service starts from the Nix-built Hermes package and the Nix store closure produced during install, avoiding Docker image pulls and in-container apt/NodeSource/Astral/uv provisioning during the installed machine's first service start.

Docker remains enabled and the container settings remain parameterized. Operators who want the upstream writable OCI tool layer can set:

```nix
containerMode = true;
```

Do that only after confirming one of:

- first boot has reliable outbound network access to the endpoints above
- `containerImage` points at a preloaded local image/tag
- a registry/apt/NodeSource/Astral/uv mirror strategy is in place

## Validation

Static CI guardrail:

```bash
tests/boot-image-static.sh
```

Nix eval guardrails in CI still evaluate the full `nixosConfigurations.hermes.config.system.build.toplevel.drvPath` derivation path.

Post-install service checks:

```bash
systemctl is-active hermes-agent
journalctl -u hermes-agent -n 100 --no-pager
hermes status
```

If `containerMode = true`, additionally check:

```bash
docker image inspect ubuntu:24.04
docker inspect hermes-agent
journalctl -u hermes-agent -n 200 --no-pager | grep -Ei 'apt-get|nodesource|astral|uv|pull|create'
```
