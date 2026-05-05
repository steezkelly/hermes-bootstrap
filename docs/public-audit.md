# Public audit notes

This document records the public-readiness audit that informed the README and configuration cleanup.

## Findings addressed

- README was written as a personal deployment log rather than a reusable project front page.
- README included hardware-specific values and one operator-specific home path.
- `system/nixos/README.md` described an older Ventoy-first/manual flow and referenced files that no longer match the current flake layout.
- `system/nixos/flake.nix` created a personal admin user with a personal description and home path.
- `scripts/deploy-hermes.sh` assumed a NixOS ISO at one operator-specific home path.
- post-install SSH examples used a personal username.
- License: Apache-2.0 (`LICENSE`), with canonical placeholder appendix text retained for GitHub license detection.

## Current public posture

- Real credential files are ignored: `data/secrets/hermes.env` is in `.gitignore`.
- The tracked credential example is `data/secrets/hermes.env.template` and contains placeholders only.
- The hardening runbook documents secret handling, destructive disk checks, backups, rollback, and live verification.
- CI validates shell syntax, deployment-readiness invariants, ShellCheck errors, Nix flake metadata, targeted NixOS module evaluation, and full NixOS toplevel derivation evaluation.
- Full `system.build.toplevel.drvPath` evaluation now passes in CI after keeping the upstream hermes-agent flake on its own nixpkgs input. The prior failure was caused by forcing hermes-agent to follow this repo's stable nixos-24.05 nixpkgs, which lacks the `tirith` package required by upstream hermes-agent.
- Live-install scripts now copy every local file imported by the target flake: `flake.nix`, `deployment-options.nix`, `agent-extra-packages.nix`, and optional `flake.lock`.
- Disk partition path handling supports both `/dev/sdX1` and NVMe/MMC-style `/dev/nvme0n1p1` / `/dev/mmcblk0p1` names.
- The target flake uses `systemd-boot` with `/boot/efi`, matching the EFI partition created by the deploy scripts.
- Target-specific `nixos-generate-config` output is preserved when available instead of being overwritten by a qemu/template hardware config.
- Gateway default in `deployment-options.nix` is localhost-only: `127.0.0.1`.
- Deployment defaults are centralized in `system/nixos/deployment-options.nix` instead of being scattered through `flake.nix`.
- Generated boot-image outputs, USB backups, and accidental root-level `auto-deploy.sh` copies are ignored; `docs/local-artifact-policy.md` documents what is ignored versus what needs human review.

## Follow-up recommendations

- Add a VM smoke test for `nixosConfigurations.hermes`.
- Split historical deployment notes from the user-facing quickstart.
- Add successful deployment transcript or screenshots.
