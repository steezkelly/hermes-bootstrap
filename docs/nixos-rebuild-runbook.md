# Hermes OS Mini-PC Deployment Runbook

Last updated: 2026-05-09, post-GPT-5.5-Pro deployability audit
Target: Mini-PC, bare metal NixOS 24.05

---

## PRE-FLIGHT CHECKS (run on the mini-PC, before nixos-rebuild)

### 1. Verify NixOS is installed and bootable
```bash
nixos-version
# Should show 24.05 or newer
```

### 2. Generate hardware-configuration.nix on the TARGET machine
The repo's `hardware-configuration.nix` assumes /dev/nvme0n1. If your mini-PC uses a different disk (SATA SSD, eMMC), regenerate:

```bash
# On the mini-PC, in the cloned repo:
sudo nixos-generate-config --root /
# This writes /etc/nixos/hardware-configuration.nix

# Then copy it into the repo:
cp /etc/nixos/hardware-configuration.nix /path/to/hermes-bootstrap/system/nixos/hardware-configuration.nix
git add system/nixos/hardware-configuration.nix
git commit -m "hardware: target-generated hardware config for mini-pc"
```

IMPORTANT: The repo's hardware-configuration.nix imports `qemu-guest.nix`. If you're on bare metal, REMOVE that import:
```nix
# Delete this line from the regenerated config:
# (modulesPath + "/profiles/qemu-guest.nix")
```

### 3. Verify filesystem partition layout
```bash
lsblk -f
# Confirm your root (/) and boot (/boot/efi) devices match what's in hardware-configuration.nix
```

### 4. Clone the bootstrap repo onto the mini-PC
```bash
cd /home/hermes-admin  # or wherever you're working
git clone https://github.com/steezkelly/hermes-bootstrap.git
cd hermes-bootstrap
```

### 5. Prepare credentials
The `secretsEnvFile` is configured as `/var/lib/hermes/secrets/hermes.env`. Format:

```bash
# /var/lib/hermes/secrets/hermes.env
MINIMAX_API_KEY=sk-your-key-here
# Add other provider keys as needed
```

BEFORE nixos-rebuild, this file must exist with the correct keys:
```bash
sudo mkdir -p /var/lib/hermes/secrets
sudo touch /var/lib/hermes/secrets/hermes.env
sudo chmod 600 /var/lib/hermes/secrets/hermes.env
# Edit and add your keys
sudo vim /var/lib/hermes/secrets/hermes.env
```

The service startup will fail if this file is missing.

### 6. Verify Foundry checkout path
The harness.nix references:
  `../../scripts/harness/../repos/steezkelly-hermes-agent-self-evolution/...`

This needs the Foundry repo checked out alongside the bootstrap repo:
```bash
cd /home/hermes-admin
git clone https://github.com/steezkelly/hermes-agent-self-evolution.git
```

The relative path resolves as: `/home/hermes-admin/repos/steezkelly-hermes-agent-self-evolution/`

If you clone it elsewhere, update the paths in `system/nixos/harness.nix` (lines referencing `../repos/`).

### 7. Confirm git state is clean
```bash
cd /home/hermes-admin/hermes-bootstrap
git status
# Should be clean. If not, commit or stash changes.
git log --oneline -3
# Should show at least: 269ddf5 fix: deterministic harnessDir path
```

---

## DEPLOY

### One command:
```bash
cd /home/hermes-admin/hermes-bootstrap
sudo nixos-rebuild switch --flake .#hermes
```

Expected output: building derivations, linking, activating. No errors.

---

## FIRST-BOOT VERIFICATION

### 1. Hermes Agent service
```bash
sudo systemctl status hermes-agent
# Should show: active (running)

sudo journalctl -u hermes-agent -n 20 --no-pager
# Look for: "Hermes Agent started" or equivalent. Errors about missing API keys = fix secrets.env first.
```

### 2. Harness services (all default-off, manual only)
```bash
sudo systemctl list-units --type=service | grep hermes-evolution
# Should show about 10 services, all "inactive" (manual start only — EXPECTED)
```

### 3. Test a manual Foundry fixture
```bash
sudo systemctl start hermes-evolution-foundry-action-routing-fixture
sudo journalctl -u hermes-evolution-foundry-action-routing-fixture --no-pager
# Should show the fixture running and completing

sudo systemctl start hermes-validate-foundry-action-routing-fixture
sudo journalctl -u hermes-validate-foundry-action-routing-fixture --no-pager
# Should show "Boundary validation passed"
```

### 4. Test the full chain (if you want to verify end-to-end)
```bash
# First, export a session from the running Hermes agent
sudo -u hermes hermes export-session --last

# Then run the manual session-end ingest
sudo systemctl start hermes-session-end-ingest
sudo journalctl -u hermes-session-end-ingest --no-pager

# Verify artifacts exist
ls -la /var/lib/hermes/reports/evolution/session-end-ingest/
```

---

## FALLBACK / ROLLBACK

If nixos-rebuild fails:
```bash
sudo nixos-rebuild switch --rollback
# This restores the previous generation
```

If the agent won't start:
1. Check `sudo systemctl status hermes-agent` for errors
2. Verify secrets file: `ls -la /var/lib/hermes/secrets/hermes.env`
3. Check journal: `sudo journalctl -u hermes-agent -n 50 --no-pager`
4. Most common failure: missing API keys in hermes.env

If the agent starts but makes no network calls:
- The `containerMode` is false (native Nix-built). This is correct.
- Verify API key validity: `cat /var/lib/hermes/secrets/hermes.env`

---

## SERVICE ARCHITECTURE REFERENCE

### WARNING: no service has a timer (all manual/default-off)
The only timed service in the config is `hermes-phase2-delivery-brief-send` and it requires `deployment.phase2DeliveryTimerEnabled = true` (currently false).

### Chain service order (if you run them sequentially):
```
hermes-session-end-ingest
  → hermes-evolution-foundry-real-trace-ingestion
  → hermes-evolution-foundry-attention-router-bridge
  → hermes-bridge-ingestion-to-attention-router
  → hermes-evolution-foundry-trace-optimizer
  → hermes-evolution-foundry-gepa-bridge
  → hermes-evolution-foundry-pipeline-runner
```

### Validators (run after their paired service):
```
hermes-validate-foundry-real-trace-ingestion
hermes-validate-foundry-attention-router-bridge
hermes-validate-foundry-trace-optimizer
hermes-validate-foundry-gepa-bridge
hermes-validate-foundry-pipeline-runner
```
