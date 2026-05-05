# Container image archives

Optional staging area for explicit `containerMode = true` deployments.

Place Docker/Podman image archives here before running `scripts/deploy-hermes.sh --bootstrap`. The bootstrap script copies `*.tar`, `*.tar.gz`, and `*.oci` files to the target's `/var/lib/hermes/container-images/`; the NixOS system then runs `hermes-container-image-preload.service` before `hermes-agent.service`.

Examples:

```bash
# Basic base-image preload. Avoids a registry pull only; the upstream entrypoint
# can still need apt, NodeSource, Astral uv, and uv Python downloads.
docker pull ubuntu:24.04
docker save ubuntu:24.04 -o data/container-images/ubuntu-24.04.tar

# Better: save a pre-provisioned image tagged to match containerImage in
# system/nixos/deployment-options.nix.
docker save hermes-agent-tools:2026-05-05 -o data/container-images/hermes-agent-tools.tar
```

Do not put credentials or API keys in image archives.
Large archives are intentionally ignored by git; keep only this README committed.
