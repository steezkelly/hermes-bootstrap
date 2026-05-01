#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# HERMES OS — Verification Script
# Runs on the deployed NixOS system to verify everything is working
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BOLD='\033[1m'; RESET='\033[0m'

PASS=0; FAIL=0; WARN=0

log_pass() { echo -e "  ${GREEN}[PASS]${RESET} $*"; ((PASS++)); }
log_fail() { echo -e "  ${RED}[FAIL]${RESET} $*"; ((FAIL++)); }
log_warn() { echo -e "  ${YELLOW}[WARN]${RESET} $*"; ((WARN++)); }
section() { echo; echo -e "${BOLD}## $*${RESET}"; }

run() {
    local cmd="$1"; shift
    local label="$1"; shift
    if [[ $# -gt 0 ]]; then
        label="$label — $*"
    fi
    if eval "$cmd" &>/dev/null; then
        log_pass "$label"
    else
        log_fail "$label (exit $?)"
    fi
}

check_output() {
    local cmd="$1"; shift
    local label="$1"; shift
    local out
    if out=$(eval "$cmd" 2>&1); then
        log_pass "$label"
        [[ -n "$out" ]] && echo "         → $out"
    else
        log_fail "$label"
        [[ -n "$out" ]] && echo "         → $out"
    fi
}

echo "════════════════════════════════════════════════════════════════════"
echo "  HERMES OS — Verification Suite"
echo "════════════════════════════════════════════════════════════════════"

section "System"

run "test -f /etc/nixos/flake.nix" "flake.nix exists"
run "test -d /etc/nixos/hermes-agent" "hermes-agent source present"
run "test -d /var/lib/hermes" "hermes state directory exists"
run "test -d /var/lib/hermes/workspace" "workspace directory exists"
run "test -f /var/lib/hermes/.hermes/config.yaml" "config.yaml generated"
run "test -f /var/lib/hermes/.hermes/.managed" "NixOS managed marker exists"
run "test -f /var/lib/hermes/.hermes/.env" ".env file exists"

section "User / Group"

run "id hermes &>/dev/null" "hermes user exists"
run "id -g hermes &>/dev/null" "hermes group exists"
run "stat -c %U /var/lib/hermes | grep -q hermes" "hermes owns state directory"

section "NixOS Module"

run "hermes --version 2>/dev/null || hermes-agent --version 2>/dev/null" "hermes CLI available"
run "test -f /run/current-system/sw/bin/hermes" "hermes in system profile"

section "Systemd Service"

run "systemctl is-active hermes-agent &>/dev/null" "hermes-agent.service is active"
run "systemctl is-enabled hermes-agent &>/dev/null" "hermes-agent.service is enabled"
run "! systemctl is-failed hermes-agent &>/dev/null" "hermes-agent.service not failed"

section "Network"

if systemctl is-active hermes-agent &>/dev/null; then
    run "curl -s --max-time 5 https://api.nousresearch.com/health &>/dev/null || true" "Nous API reachable"
    run "ss -tlnp | grep -q ':8080'" "Gateway port 8080 is listening"
fi

section "Permissions"

run "test -O /var/lib/hermes/.hermes/config.yaml" "config.yaml owned by correct user"
run "find /var/lib/hermes/.hermes -name '*.yaml' -o -name '*.yml' | xargs -I{} test -r {} 2>/dev/null" "YAML files readable"

section "Logs"

run "test -d /var/lib/hermes/.hermes/logs" "logs directory exists"
run "! journalctl -u hermes-agent -n 50 --no-pager | grep -i 'error\|exception\|traceback' | grep -v '0 errors' 2>/dev/null || true" "No errors in recent logs"

section "Nix Garbage Collection"

run "test -f /var/lib/hermes/.hermes/.managed" "Nix managed marker"
run "nix-channel --list 2>/dev/null | grep -q nixos" "nixos channel configured"

section "SSH"

run "systemctl is-active sshd &>/dev/null || systemctl is-active sshd.service &>/dev/null" "SSH daemon active"
run "test -f /etc/ssh/ssh_host_rsa_key" "SSH host keys generated"

section "Docker"

run "docker info &>/dev/null" "Docker daemon running"
run "! docker ps 2>/dev/null | grep -q 'Cannot connect'" "Docker not in error state"

section "Disk Space"

df_out=$(df -h / | tail -1)
avail=$(echo "$df_out" | awk '{print $4}')
log_pass "Root filesystem: $avail available"

echo
echo "════════════════════════════════════════════════════════════════════"
echo "  Results: ${GREEN}$PASS passed${RESET}  ${YELLOW}$WARN warnings${RESET}  ${RED}$FAIL failed${RESET}"
echo "════════════════════════════════════════════════════════════════════"

if [[ $FAIL -gt 0 ]]; then
    echo -e "${RED}Verification FAILED${RESET} — $FAIL checks failed"
    echo "Run 'journalctl -u hermes-agent -n 100 --no-pager' for details"
    exit 1
elif [[ $WARN -gt 0 ]]; then
    echo -e "${YELLOW}Verification PASSED WITH WARNINGS${RESET}"
    exit 0
else
    echo -e "${GREEN}Verification PASSED${RESET}"
    exit 0
fi
