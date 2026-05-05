# Container Mode Prewarm Findings

This note records the explicit `containerMode = true` hardening trace. The default installed runtime remains native first boot (`containerMode = false`).

## Upstream Dependency Trace

- Local system entrypoint: `system/nixos/flake.nix` imports `hermes-agent.nixosModules.default` and wires `services.hermes-agent.container.enable = deployment.containerMode`.
- Local deployment defaults: `system/nixos/deployment-options.nix` keeps `containerMode = false`, `containerBackend = "docker"`, and `containerImage = "ubuntu:24.04"`.
- Lock trace: `system/nixos/flake.lock` pins `NousResearch/hermes-agent` at `d12f59aa5377635f7f4ad680cc349bf3e770a5d8`.
- Upstream file at that revision: `nix/nixosModules.nix`.
- Upstream mode split: `container.enable = false` creates a native hardened `hermes-agent.service`; `container.enable = true` replaces it with a persistent OCI container service.
- Container startup path when enabled:
  - systemd waits for `network-online.target` and Docker when `backend = "docker"`.
  - `preStart` creates stable symlinks in `stateDir`, creates Nix GC roots, checks container identity, and runs `docker create`/`podman create` if the container does not exist or identity changed.
  - If `container.image` is absent locally, runtime creation can pull it during first service start.
  - Default image is `ubuntu:24.04`.
  - Container mounts `/nix/store` read-only, `stateDir` at `/data`, `stateDir/home` at `/home/hermes`, and optional `container.extraVolumes`.
  - Entrypoint provisions on first boot inside the writable layer: user/group, `apt-get update`, `sudo`, `curl`, `ca-certificates`, `gnupg`, NodeSource GPG/source, `nodejs`, uv installer from `https://astral.sh/uv/install.sh`, `uv python install 3.12`, and a seeded Python venv.
- Resulting first-boot network dependencies for explicit container mode: Docker registry or mirror for the base image, Ubuntu apt mirrors, NodeSource, Astral uv installer, and uv's Python download source.

## Upstream Module Options Available

Confirmed from the pinned upstream module/docs:

- Core: `enable`, `package`, `user`, `group`, `createUser`, `stateDir`, `workingDirectory`, `addToSystemPackages`.
- Config/secrets/documents: `settings`, `configFile`, `environmentFiles`, `environment`, `authFile`, `authFileForceOverwrite`, `documents`, `mcpServers`.
- Service behavior: `extraArgs`, `extraPackages`, `extraPlugins`, `extraPythonPackages`, `restart`, `restartSec`.
- Container:
  - `container.enable`: explicit OCI mode switch; upstream default is false.
  - `container.backend`: `"docker"` or `"podman"`.
  - `container.image`: base image, default `"ubuntu:24.04"`, pulled by runtime if missing.
  - `container.extraVolumes`: extra `host:container:mode` mounts.
  - `container.extraOptions`: additional args to `docker create`/`podman create`.
  - `container.hostUsers`: users given a `~/.hermes` symlink to shared service state and added to the Hermes group.

Notably absent upstream: a module option to skip first-boot provisioning, a declarative apt/npm/pip package list, a container image archive/preload option, configurable apt/NodeSource/Astral mirrors, or service-level gating on local image presence.

## Viable Repo-Local Fixes

- Add explicit container-mode preflight to deployment/verification scripts:
  - Detect `containerMode = true` from `system/nixos/deployment-options.nix`.
  - Warn or fail before reboot if the target will need a runtime image pull and in-container provisioning.
  - Check `docker image inspect "$containerImage"` or `podman image exists "$containerImage"` where the runtime is available.
  - Print the exact external endpoints needed for cold start.
- Add optional image archive preload support:
  - Convention: allow an operator to place OCI archives under a repo-local path such as `data/container-images/`.
  - During bootstrap, if `containerMode = true`, copy archives to the target or load them into the target runtime with `docker load`/`podman load`.
  - Keep it optional so native first boot remains unchanged.
- Add documentation for a supported explicit-container workflow:
  - Keep current `containerMode = false` default.
  - For `containerMode = true`, require either reliable outbound network, a local preloaded `containerImage`, or a private registry/mirror strategy.
  - Document post-install checks: `docker image inspect`, `docker inspect hermes-agent`, and logs filtered for `apt-get`, `nodesource`, `astral`, `uv`, `pull`, and `create`.
- Add static tests around any new preflight/preload wiring:
  - Assert native default remains `containerMode = false`.
  - Assert any new preload logic is conditional on explicit container mode.
  - Assert the warning mentions image pull plus apt/NodeSource/Astral/uv provisioning.
- Consider making `scripts/verify-bootstrap.sh` container-aware:
  - Docker daemon checks are currently unconditional.
  - A safer verification split would check Docker only when Docker is enabled or when `containerMode = true`, then add deeper container checks only for explicit container mode.

## Risky Fixes To Avoid

- Do not change `containerMode` back to true by default; that reintroduces first-boot network fragility for the native install path.
- Do not patch the upstream module inline in this repo unless there is a clear vendoring strategy. The current flake imports upstream directly from the lock.
- Do not try to silence the upstream entrypoint by touching sentinel files such as `/var/lib/hermes-tools-provisioned`; that can leave a container without sudo, curl, Node, uv, or a writable Python environment.
- Do not rely on `container.extraOptions = [ "--pull=never" ]` alone. It may fail fast when the image is missing, but it does not prewarm apt/NodeSource/Astral/uv and may not be portable across runtime versions.
- Do not bake secrets into a custom image or Nix store path. Keep API keys in `environmentFiles`.
- Do not use mutable tags as a reproducibility promise. `ubuntu:24.04` can move; a digest-pinned image is better for repeatable preloads, but digest changes still recreate the container and lose writable-layer packages.
- Do not assume a preloaded Ubuntu image makes first start network-independent. The entrypoint can still need apt mirrors, NodeSource, Astral, and uv Python downloads unless the image already contains the required tools in the expected locations.

## Implemented Minimal PR

This hardening pass makes explicit container mode safer without changing default native first boot:

1. `scripts/deploy-hermes.sh` runs `container_mode_preflight` after copying NixOS flake files. When `containerMode = false`, it exits early. When `containerMode = true`, it reports the configured backend/image, warns about cold-start network endpoints, and stages any `data/container-images/*.tar`, `*.tar.gz`, or `*.oci` archives into `containerImageArchiveDir`.
2. `system/nixos/flake.nix` defines `hermes-container-image-preload.service` behind `lib.mkIf deployment.containerMode`; the service runs before `hermes-agent.service` and loads staged archives with Docker or Podman.
3. `docs/first-boot-network.md` and `docs/hardening-runbook.md` document the prewarm flow and the caveat that image preload alone does not cover in-container apt/NodeSource/Astral/uv unless the image is pre-provisioned.
4. Static and unit tests prove native default remains false, preload logic is conditional, and the bootstrap preflight copies archives without needing a real image.

This keeps the current safe default intact, gives operators who explicitly choose `containerMode = true` a deterministic preflight/preload path, and avoids unstable local forks of the upstream NixOS module.
