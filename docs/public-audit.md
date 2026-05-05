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
- CI validates shell syntax, ShellCheck errors, and Nix flake metadata.
- Gateway default in `flake.nix` is localhost-only: `127.0.0.1`.

## Follow-up recommendations

- Parameterize deployment defaults instead of hardcoding hostname, provider, model, admin username, and gateway host.
- Add a VM smoke test for `nixosConfigurations.hermes`.
- Split historical deployment notes from the user-facing quickstart.
- Add successful deployment transcript or screenshots.
- Add GitHub topics: `hermes-agent`, `nixos`, `self-hosted`, `ai-agent`, `agent-infrastructure`, `declarative-infrastructure`, `automation`.
