# Public audit notes

This document records the public-readiness audit that informed the README and configuration cleanup.

## Findings addressed

- README was written as a personal deployment log rather than a reusable project front page.
- README included hardware-specific values and one operator-specific home path.
- `system/nixos/README.md` described an older Ventoy-first/manual flow and referenced files that no longer match the current flake layout.
- `system/nixos/flake.nix` created a personal admin user with a personal description and home path.
- `scripts/deploy-hermes.sh` assumed a NixOS ISO at one operator-specific home path.
- post-install SSH examples used a personal username.
- License: Apache-2.0 (`LICENSE`).

## Current public posture

- Real credential files are ignored: `data/secrets/hermes.env` is in `.gitignore`.
- The tracked credential example is `data/secrets/hermes.env.template` and contains placeholders only.
- The hardening runbook documents secret handling, destructive disk checks, backups, rollback, and live verification.
- CI validates shell syntax, ShellCheck errors, Nix flake metadata, and targeted NixOS module evaluation.
- Targeted NixOS module evaluation caught and fixed latent config issues: a `networking.useDHCP` conflict with generated hardware configuration, invalid `pkgs.make`, invalid standalone `pkgs.npm`, and invalid GNU utility package references.
- Full `system.build.toplevel.drvPath` evaluation is intentionally not in CI yet because the upstream hermes-agent flake package currently aborts on a missing `tirith` argument before this repo's system config can finish evaluating.
- Gateway default in `deployment-options.nix` is localhost-only: `127.0.0.1`.
- Deployment defaults are centralized in `system/nixos/deployment-options.nix` instead of being scattered through `flake.nix`.

## Follow-up recommendations

- Add a VM smoke test for `nixosConfigurations.hermes`.
- Split historical deployment notes from the user-facing quickstart.
- Add successful deployment transcript or screenshots.
- Add GitHub topics: `hermes-agent`, `nixos`, `self-hosted`, `ai-agent`, `agent-infrastructure`, `declarative-infrastructure`, `automation`.
