#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

fail() {
  echo "$*" >&2
  exit 1
}

assert_contains() {
  local file="$1"
  local pattern="$2"
  grep -Eq "$pattern" "$file" || fail "Missing expected pattern in $file: $pattern"
}

assert_not_contains() {
  local file="$1"
  local pattern="$2"
  if grep -Eq "$pattern" "$file"; then
    fail "Unexpected pattern in $file: $pattern"
  fi
}

for script in \
  "$repo_root/scripts/harness/harness_common.py" \
  "$repo_root/scripts/harness/system_health_sensor.py" \
  "$repo_root/scripts/harness/network_health_sensor.py" \
  "$repo_root/scripts/harness/hermes_health_sensor.py" \
  "$repo_root/scripts/harness/release_policy_sensor.py" \
  "$repo_root/scripts/harness/node_health_watchdog.py" \
  "$repo_root/scripts/harness/render_daily_report.py" \
  "$repo_root/scripts/harness/render_delivery_brief.py" \
  "$repo_root/scripts/harness/send_delivery_brief.py"; do
  [[ -s "$script" ]] || fail "Missing harness script: $script"
  python3 -m py_compile "$script"
done

PYTHONPATH="$repo_root/scripts/harness" python3 - <<'PY'
import harness_common
import hermes_health_sensor
import network_health_sensor
import node_health_watchdog
import release_policy_sensor
import render_daily_report
import system_health_sensor
print("harness scripts importable")
PY

assert_contains "$repo_root/docs/node-harness-phase1.md" 'No Hermes cron'
assert_contains "$repo_root/docs/node-harness-phase1.md" 'No Kanban'
assert_contains "$repo_root/docs/node-harness-phase1.md" 'No LLM'
assert_contains "$repo_root/docs/node-harness-phase1.md" 'No messaging'
assert_contains "$repo_root/docs/node-harness-phase1.md" 'No mutation'
assert_contains "$repo_root/docs/node-harness-phase1.md" 'No secrets access'

assert_contains "$repo_root/system/nixos/harness.nix" 'writeShellApplication'
assert_contains "$repo_root/system/nixos/harness.nix" 'hermes-harness'
assert_contains "$repo_root/system/nixos/harness.nix" 'OnBootSec = "5min";'
assert_contains "$repo_root/system/nixos/harness.nix" 'OnUnitActiveSec = "30min";'
assert_not_contains "$repo_root/system/nixos/harness.nix" 'Persistent = true;[[:space:]]*#.*watchdog'
assert_contains "$repo_root/system/nixos/harness.nix" 'OnCalendar = "\*-\*-\* 06:00:00";'
assert_contains "$repo_root/system/nixos/harness.nix" 'Persistent = true;'
assert_contains "$repo_root/system/nixos/harness.nix" 'InaccessiblePaths = \[ "-/var/lib/hermes/secrets" \];'
assert_contains "$repo_root/system/nixos/harness.nix" 'StateDirectory = "hermes/delivery/state";'
assert_contains "$repo_root/system/nixos/harness.nix" 'StateDirectoryMode = "2770";'
assert_contains "$repo_root/system/nixos/flake.nix" '\./harness\.nix'
assert_contains "$repo_root/.github/workflows/ci.yml" 'tests/harness_phase1_static\.sh'
assert_contains "$repo_root/.github/workflows/ci.yml" 'python3 -m pytest -q'
assert_not_contains "$repo_root/system/nixos/harness.nix" 'User[[:space:]]*=[[:space:]]*"hermes-admin"'
assert_not_contains "$repo_root/system/nixos/harness.nix" 'RemainAfterExit[[:space:]]*='
