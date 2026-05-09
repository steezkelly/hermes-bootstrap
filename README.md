# Hermes Bootstrap

Hermes Bootstrap is a NixOS deployment kit for running Hermes Agent on hardware you control.

It turns a small server, mini PC, or spare x86_64 machine into a reproducible, self-owned AI agent node:

- NixOS system definition in `system/nixos/flake.nix`
- Hermes Agent managed by systemd
- isolated `/var/lib/hermes` state directory for memory, logs, skills, wiki, and workspace
- provider credentials loaded from a root-owned env file, not committed config
- native first-boot runtime by default, with optional container mode after cache/network provisioning
- local Phase 1 observability harness: systemd timers, deterministic sensors, JSONL events, and daily Markdown reports
- USB/NixOS installer workflows plus hardening and rollback notes

This repository is intentionally infrastructure-focused. It does not include private memories, private wiki content, real API keys, or personal workspace data.

## Status

Public prototype / operator toolkit.

The repo has been used as a real deployment workbench, so some scripts are still opinionated. The public goal is to make those opinions explicit, safe, and configurable rather than hidden in local state.

Current defaults are centralized in `system/nixos/deployment-options.nix`:

| Area | Default |
|---|---|
| Target architecture | x86_64-linux |
| OS | NixOS 24.05 |
| Agent | NousResearch/hermes-agent flake input |
| Service user | `hermes` |
| Interactive admin user | `hermes-admin` |
| Hostname | `hermes-node` |
| Gateway bind address | `127.0.0.1` |
| Provider example | MiniMax via `/var/lib/hermes/secrets/hermes.env` |
| Local harness | `hermes-harness` system user, systemd timers, `/var/lib/hermes/{harness,events,reports}` |

Edit `system/nixos/deployment-options.nix` before deployment to change host identity, admin account, provider/model defaults, gateway binding, locale, or the secrets env-file path.

## Architecture

```text
Linux build/admin machine
  |
  | prepares USB / copies repo / bundles hermes-agent source
  v
USB installer media
  |
  | boots target machine into NixOS installer or bootstrap environment
  v
Target machine internal disk
  |
  | NixOS + systemd + Hermes Agent + local harness timers
  v
/var/lib/hermes
  |- .hermes/        runtime config, logs, sessions, memory
  |- workspace/      agent working directory
  |- secrets/        provider credentials, mode 0600, never committed
  |- wiki/           optional private knowledge base seed
  |- skills/         optional skill seed
  |- harness/        latest deterministic local sensor snapshot
  |- events/         bounded harness event JSONL
  |- reports/        daily local Markdown reports
  `- backups/        local backup target
```

Runtime posture:

- SSH is enabled, root login disabled.
- Hermes gateway binds to localhost by default.
- Public internet exposure is out of scope unless you add a reviewed reverse proxy/TLS layer.
- The agent has broad local power by design; use this on machines you are willing to dedicate to agent work.

## Repository layout

```text
hermes-bootstrap/
├── README.md
├── SPEC.md
├── .github/workflows/ci.yml
├── boot-image/
│   ├── make-boot-image.sh
│   └── overlay/
│       ├── auto-deploy.sh
│       └── usr/local/bin/{hw-detect,wifi-setup}
├── boot/ventoy/ventoy.json
├── data/
│   ├── memory/.gitkeep
│   ├── secrets/hermes.env.template
│   ├── skills/.gitkeep
│   ├── tools/.gitkeep
│   └── wiki/.gitkeep
├── docs/
│   ├── deployment-skill.md
│   ├── hardening-runbook.md
│   ├── install-manual-nixos.md
│   ├── local-artifact-policy.md
│   ├── node-harness-phase1.md
│   ├── phase1-live-validation.md
│   ├── phase2-boundaries.md
│   ├── symbiosis-assimilation.md
│   └── public-audit.md
├── scripts/
│   ├── backup-memories.py
│   ├── create-nixos-findiso-usb.sh
│   ├── deploy-hermes.sh
│   ├── harness/
│   ├── setup-hermes-agent.sh
│   ├── update-nixos-usb-autodeploy.sh
│   └── verify-bootstrap.sh
├── system/nixos/
│   ├── agent-extra-packages.nix
│   ├── deployment-options.nix
│   ├── flake.nix
│   ├── harness.nix
│   ├── hardware-configuration.nix
│   └── README.md
└── tests/
    ├── deployment-readiness.sh
    ├── findiso-autodeploy-static.sh
    ├── harness_phase1_static.sh
    ├── harness_phase1_fixtures.py
    └── shell-syntax.sh
```

## Prerequisites

On the build/admin machine:

- Linux shell environment
- Git
- Nix, if you want to validate the flake locally
- ShellCheck, if you want to run shell lint locally
- Python + pytest, if you want to run the Phase 1 harness behavior tests
- Docker, only if building the experimental Alpine boot image
- a NixOS minimal ISO for manual installer flows
- a target x86_64 machine whose disk can be erased

Danger zone: deployment scripts can partition and format disks. Always identify devices live with:

```bash
lsblk -o NAME,SIZE,MODEL,SERIAL,TRAN,FSTYPE,MOUNTPOINTS
sudo blkid
```

Never rely on remembered device names.

## Quick start: review and prepare

```bash
git clone https://github.com/steezkelly/hermes-bootstrap.git
cd hermes-bootstrap

# Optional but recommended: validate scripts and flake/module evaluation.
tests/shell-syntax.sh
tests/findiso-autodeploy-static.sh
tests/deployment-readiness.sh
tests/harness_phase1_static.sh
python3 -m pytest -q
shellcheck --severity=error scripts/*.sh boot-image/*.sh boot-image/overlay/auto-deploy.sh boot-image/overlay/usr/local/bin/hw-detect boot-image/overlay/usr/local/bin/wifi-setup
nix flake metadata ./system/nixos --accept-flake-config
nix eval ./system/nixos#nixosConfigurations.hermes.config.networking.hostName --accept-flake-config
nix eval --expr 'let flake = builtins.getFlake (toString ./system/nixos); pkgs = import flake.inputs.nixpkgs { system = "x86_64-linux"; }; in builtins.length (import ./system/nixos/agent-extra-packages.nix { inherit pkgs; })' --accept-flake-config --impure
nix eval ./system/nixos#nixosConfigurations.hermes.config.system.build.toplevel.drvPath --accept-flake-config

# Bundle a local hermes-agent checkout if you want an offline/local-source install.
./scripts/setup-hermes-agent.sh --copy /path/to/hermes-agent

# Review hardening, Phase 2 delivery, Symbiosis assimilation, and Foundry wrapper notes before touching hardware.
less docs/hardening-runbook.md
less docs/phase2-boundaries.md
less docs/symbiosis-assimilation.md
less docs/foundry-dry-run-wrapper.md
```

## Deployment paths

There are two practical paths in this repo.

### Path A: NixOS installer USB plus deploy script

This is the most understandable path for humans to audit. The detailed walkthrough is `docs/install-manual-nixos.md`.

1. Put the NixOS minimal ISO and this repository on USB media.
2. Boot the target machine into the NixOS installer.
3. Run the deploy script from the installer environment.

Example commands inside the installer, after the USB is mounted and this repo is available:

```bash
cd /path/to/hermes-bootstrap

# Destroys the selected target disk after confirmation.
sudo ./scripts/deploy-hermes.sh --partition /dev/nvme0n1

# Installs NixOS + Hermes Agent onto the mounted target.
sudo ./scripts/deploy-hermes.sh --bootstrap /dev/nvme0n1 /path/to/hermes-bootstrap
```

### Path B: NixOS findiso USB autodeploy

This is the current live-hardware path for a mostly plug-and-play install. It keeps the NixOS minimal ISO on a FAT32 USB as `nixos-minimal.iso`, boots it with GRUB `findiso=`, mounts the same USB at `/run/hermes-usb`, and runs `scripts/deploy-hermes.sh --auto-live` from `systemd.run`.

```bash
# Create a new FAT32 NIXOS-BOOT USB. Destructive: formats the selected disk.
sudo ./scripts/create-nixos-findiso-usb.sh /dev/sdX /path/to/nixos-minimal-24.05-x86_64-linux.iso

# Refresh an existing NIXOS-BOOT USB without repartitioning/reformatting.
sudo ./scripts/update-nixos-usb-autodeploy.sh /dev/sdX
```

Live-deployment guardrails:

- Intel N100/N150-class machines use `module_blacklist=i915` on the installer kernel line to avoid early i915 boot hangs.
- `systemd.run` entries are separate commands: create `/run/hermes-usb`, mount `LABEL=NIXOS-BOOT`, then invoke `bash deploy-hermes.sh --auto-live` with an explicit PATH.
- The GRUB `linux` line must use unwrapped `systemd.run="/run/... args"` tokens. Do not surround those tokens with single quotes and do not emit literal `\"`; both forms can make systemd treat the whole command string as the executable.
- Do not set `HERMES_LIVE_TTY=1` in GRUB. The live script sets it only after attaching stdin/stdout/stderr to `/dev/tty1`, so SSID/password prompts can be typed without relying on `openvt`.
- The USB update/create scripts self-check the generated command line with `systemd-run-generator` when available.

### Path C: experimental boot image

`boot-image/make-boot-image.sh` builds an Alpine-based bootstrap image intended to automate more of the process.

```bash
cd boot-image
sudo ./make-boot-image.sh --size 256M --output hermes-boot.img --force-rootfs
cd ..
tests/boot-image-smoke.sh boot-image/hermes-boot.img
```

The smoke test is non-destructive: it reads the image with mtools, validates MBR/GPT/FAT contents, and checks `/EFI/BOOT/BOOTX64.EFI` plus `grub.cfg`. It does not write a USB device. See `docs/boot-image-smoke-tests.md`.

This path is more hardware-sensitive. See `SPEC.md` and `docs/deployment-skill.md` for known USB, UEFI, Ventoy, and N100-class hardware notes.

### First-boot runtime mode

The installed service defaults to native first boot (`containerMode = false` in `system/nixos/deployment-options.nix`). This avoids a post-install dependency on Docker Hub, Ubuntu apt, NodeSource, Astral uv, and `uv python install` before `hermes-agent.service` can start. Enable container mode only after provisioning network/cache for the upstream writable OCI tool layer. Optional image archives placed in `data/container-images/` are staged and loaded before `hermes-agent.service` on explicit container-mode systems. See `docs/first-boot-network.md`.

## Credentials

Do not paste real API keys into shell commands or commit them to this repo.

The target system expects credentials at:

```text
/var/lib/hermes/secrets/hermes.env
```

Create/edit it safely after install:

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

The tracked template is `data/secrets/hermes.env.template`; the real `data/secrets/hermes.env` is ignored by Git.

## Post-install checks

```bash
systemctl is-active hermes-agent
journalctl -u hermes-agent -n 100 --no-pager
hermes status
hermes tools list
sudo ss -tlnp | grep -E ':22|:8080'
sudo stat -c '%U:%G %a %n' /var/lib/hermes/secrets /var/lib/hermes/secrets/hermes.env
systemctl list-timers 'hermes-*' --no-pager
sudo systemctl start hermes-node-health-watchdog.service
sudo systemctl start hermes-daily-local-brief.service
```

Expected network posture:

- SSH is reachable only where intended.
- Hermes gateway is bound to `127.0.0.1` unless you deliberately changed it.
- Phase 1 harness outputs are readable to the `hermes` group under `/var/lib/hermes/{harness,events,reports}`.

For the full hardware checklist, use `docs/phase1-live-validation.md`.
For the next push-delivery design boundary, use `docs/phase2-boundaries.md`.

## Validation

CI currently runs:

- Bash syntax checks via `tests/shell-syntax.sh`
- ShellCheck with `--severity=error`
- Phase 1 harness static checks via `tests/harness_phase1_static.sh`
- Python harness behavior tests via `pytest`
- `nix flake metadata ./system/nixos --accept-flake-config`
- targeted NixOS module/config evaluation for deployment defaults and package references

Local equivalent:

```bash
tests/shell-syntax.sh
tests/deployment-readiness.sh
tests/findiso-autodeploy-static.sh
tests/boot-image-static.sh
tests/container-mode-static.sh
tests/container-mode-preflight-unit.sh
tests/harness_phase1_static.sh
python3 -m pytest -q
shellcheck --severity=error scripts/*.sh boot-image/*.sh boot-image/overlay/auto-deploy.sh boot-image/overlay/usr/local/bin/hw-detect boot-image/overlay/usr/local/bin/wifi-setup
nix flake metadata ./system/nixos --accept-flake-config
nix eval ./system/nixos#nixosConfigurations.hermes.config.networking.hostName --accept-flake-config
nix eval --expr 'let flake = builtins.getFlake (toString ./system/nixos); pkgs = import flake.inputs.nixpkgs { system = "x86_64-linux"; }; in builtins.length (import ./system/nixos/agent-extra-packages.nix { inherit pkgs; })' --accept-flake-config --impure
nix eval ./system/nixos#nixosConfigurations.hermes.config.system.build.toplevel.drvPath --accept-flake-config
```

## Hardening and rollback

Read `docs/hardening-runbook.md` before deploying to real hardware. It covers:

- credential handling
- destructive disk checks
- backups before rebuild/reinstall
- NixOS rollback
- live verification checks
- Phase 1 harness live validation
- gateway/SSH exposure assumptions

## Roadmap

Near-term cleanup that would make this easier for others to reuse:

- add a VM-based smoke test for the NixOS configuration and Phase 1 timers
- replace historical hardware-specific notes with a cleaner compatibility matrix
- document a fully automated boot-image path separately from the manual installer path
- add screenshots or terminal transcripts of a successful install
- implement Phase 2 push delivery only after Phase 1 live validation remains stable and `docs/phase2-boundaries.md` is resolved

## License

Apache-2.0. See `LICENSE`.

## Safety note

This project is for self-hosted agent infrastructure. It intentionally gives the agent a powerful execution environment. Treat deployments as privileged systems: isolate them, back them up, review secrets handling, and do not expose services publicly without a separate security review.
