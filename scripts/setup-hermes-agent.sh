#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# HERMES BOOTSTRAP — Setup hermes-agent source
# ═══════════════════════════════════════════════════════════════════════════
# Run this once to link/copy the hermes-agent source into the bootstrap.
# This MUST be done before deploying — the flake references it as a path.
#
# USAGE:
#   ./setup-hermes-agent.sh [--link] [/path/to/hermes-agent]
#   ./setup-hermes-agent.sh --copy /path/to/hermes-agent
#
# If hermes-agent path not provided, defaults to ~/.hermes/hermes-agent
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOTSTRAP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET_DIR="$BOOTSTRAP_ROOT/system/nixos/hermes-agent-src"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
RESET='\033[0m'

MODE="link"

# Parse args
while [[ $# -gt 0 ]]; do
    case "$1" in
        --link) MODE="link"; shift ;;
        --copy) MODE="copy"; shift ;;
        -h|--help) echo "Usage: $0 [--link|--copy] [/path/to/hermes-agent]"; exit 0 ;;
        *) SOURCE="$1"; shift ;;
    esac
done

SOURCE="${SOURCE:-$HOME/.hermes/hermes-agent}"

if [[ ! -d "$SOURCE" ]]; then
    echo -e "${RED}[ERROR]${RESET} hermes-agent source not found at: $SOURCE"
    echo "Please provide the path to your hermes-agent checkout:"
    echo "  $0 /path/to/hermes-agent"
    exit 1
fi

echo -e "${GREEN}[SETUP]${RESET} hermes-agent source: $SOURCE"
echo -e "${GREEN}[SETUP]${RESET} Target: $TARGET_DIR"
echo -e "${GREEN}[SETUP]${RESET} Mode: $MODE"

# Remove existing
if [[ -L "$TARGET_DIR" ]] || [[ -d "$TARGET_DIR" ]]; then
    echo -e "${YELLOW}[SETUP]${RESET} Removing existing hermes-agent-src..."
    rm -rf "$TARGET_DIR"
fi

case "$MODE" in
    link)
        echo -e "${GREEN}[SETUP]${RESET} Creating symlink..."
        ln -s "$SOURCE" "$TARGET_DIR"
        echo -e "${GREEN}[SETUP]${RESET} Linked: $TARGET_DIR → $SOURCE"
        ;;
    copy)
        echo -e "${GREEN}[SETUP]${RESET} Copying hermes-agent source (this may take a minute)..."
        cp -r "$SOURCE" "$TARGET_DIR"
        echo -e "${GREEN}[SETUP]${RESET} Copied: $TARGET_DIR ($(du -sh "$TARGET_DIR" | cut -f1))"
        ;;
esac

# Verify critical files exist
echo -e "${GREEN}[SETUP]${RESET} Verifying hermes-agent source..."
for f in flake.nix pyproject.toml uv.lock; do
    if [[ -f "$TARGET_DIR/$f" ]]; then
        echo -e "  ${GREEN}✓${RESET} $f"
    else
        echo -e "  ${RED}✗${RESET} $f MISSING — this is a problem"
        exit 1
    fi
done

echo ""
echo -e "${GREEN}[SETUP]${RESET} Done! hermes-agent source is ready."
echo ""
echo "Next steps:"
echo "  1. (Optional) Build hermes-boot.img:"
echo "       cd boot-image/ && sudo ./make-boot-image.sh"
echo "  2. Run: sudo ./scripts/deploy-hermes.sh --prepare-usb /dev/sdX"
echo "  3. Boot target from USB"
echo "  4. On target: sudo ./hermes-bootstrap/scripts/deploy-hermes.sh --partition /dev/nvme0n1"
echo "  5. On target: sudo ./hermes-bootstrap/scripts/deploy-hermes.sh --bootstrap /dev/nvme0n1"
echo ""
echo "Or (with hermes-boot.img):"
echo "  1. sudo dd if=boot-image/hermes-boot.img of=/dev/sdX bs=4M"
echo "  2. Boot target — auto-deploy.sh runs automatically"
echo ""
echo "To update hermes-agent on the deployed system:"
echo "  cd /etc/nixos/hermes-agent && git pull"
echo "  sudo nixos-rebuild switch --flake /etc/nixos"
