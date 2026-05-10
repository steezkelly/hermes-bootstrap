# DB Provisioning Path for Observatory Deploys

Last updated: 2026-05-10
Context: First observatory health run against real smoke-test DB on mini-PC (192.168.1.201)

## The DB

- Source: `/home/steve/judge_audit_log.db` on desktop (Droenix)
- Size: 24KB
- Rows: 3 (generation=1, skill="smoke-test", model=minimax/minimax-m2.7)
- Schema: `judge_audit_log` table with columns:
  `id, timestamp, generation, skill_name, model_used, task_id,
   expected_behavior, actual_behavior, rubric, raw_score, latency_ms,
   token_cost_estimate, error_flag, skill_body_hash, session_id`
- Extra columns vs expected: `skill_body_hash`, `session_id` (benign —
  observatory CLI gracefully ignores them)

## Deploy steps (single-shot for a new DB)

```bash
# 1. Copy DB to mini-PC
scp /home/steve/judge_audit_log.db hermes-admin@192.168.1.201:/tmp/

# 2. Move to target path, set ownership
ssh hermes-admin@192.168.1.201 '
  sudo mkdir -p /var/lib/hermes/reports/evolution/observatory &&
  sudo mv /tmp/judge_audit_log.db /var/lib/hermes/reports/evolution/observatory/judge_audit_log.db &&
  sudo chown hermes:hermes /var/lib/hermes/reports/evolution/observatory/judge_audit_log.db
'

# 3. Verify
ssh hermes-admin@192.168.1.201 '
  ls -la /var/lib/hermes/reports/evolution/observatory/judge_audit_log.db
'
```

## Future provisioning: GEPA pipeline integration

When GEPA evolution runs produce new `judge_audit_log.db` files, they will
write directly to `/var/lib/hermes/reports/evolution/observatory/judge_audit_log.db`
via the observatory logger module. No manual scp needed for production runs.

For now (2026-05-10), the DB is manually provisioned from the smoke-test
output. This path should be replaced by:

1. Run GEPA evolution chain (skill → dataset → optimize → judge)
2. Observatory logger writes to target DB automatically
3. Observatory health wrapper reads the same DB
4. No manual provisioning needed

## Observatory health invocation

### Direct (on mini-PC, with deps):

```bash
nix-shell -p python311Packages.numpy python311Packages.scikit-learn --run '
  cd /var/lib/hermes/foundry/hermes-agent-self-evolution &&
  python3 -m evolution.core.observatory.cli \
    --db-path /var/lib/hermes/reports/evolution/observatory/judge_audit_log.db \
    health --json
'
```

### Via Bootstrap wrapper service:

```bash
# Manual (expected to fail with DEAD_ZONE alert — exit 1 is correct)
sudo systemctl start hermes-evolution-foundry-observatory-health

# Validate output boundaries
sudo systemctl start hermes-validate-foundry-observatory-health

# Check output
cat /var/lib/hermes/reports/evolution/observatory/health.json
```

### Pitfall: exit 1 ≠ failure

The observatory health CLI exits 1 when alerts are present. This is by design —
JSON output is still valid and complete. systemd marks the service as "failed"
with `exit-code=1/FAILURE`, but the health.json artifact was written correctly.
The validator service confirms: `VALIDATION PASSED`.

To avoid the false alarm in future automated chains, either:
- Wrap the service in a `oneshot + RemainAfterExit=yes` config
- Or run the wrapper as a shell command outside systemd, checking only the
  validator exit code for actual health status

## Dependency note

The mini-PC system Python (3.11.10) lacks numpy and scikit-learn. These are
available in the Nix store but not on Python's path. Options:

1. `nix-shell -p` for manual runs (used here — works)
2. Add to systemPackages in the Nix config (requires flake rebuild)
3. Create a dedicated venv on the mini-PC (requires writable path)

For production, option 2 is preferred — add `python311Packages.numpy` and
`python311Packages.scikit-learn` to `environment.systemPackages` in the
NixOS config.

## Artifacts

- `/var/lib/hermes/reports/evolution/observatory/judge_audit_log.db` — 24KB
- `/var/lib/hermes/reports/evolution/observatory/health.json` — observatory health report
