#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
flake="$repo_root/system/nixos/flake.nix"
options="$repo_root/system/nixos/deployment-options.nix"
deploy="$repo_root/scripts/deploy-hermes.sh"
readme="$repo_root/data/container-images/README.md"

assert_contains() {
  local file="$1"
  local pattern="$2"
  if ! grep -Eq -- "$pattern" "$file"; then
    echo "Missing expected pattern in $file: $pattern" >&2
    exit 1
  fi
}

# Native first boot must remain the default.
assert_contains "$options" 'containerMode = false;'
assert_contains "$options" 'containerImageArchiveDir = "/var/lib/hermes/container-images";'

# Explicit container mode gets a preload service, but only behind deployment.containerMode.
assert_contains "$flake" 'systemd\.services\.hermes-container-image-preload = lib\.mkIf deployment\.containerMode'
assert_contains "$flake" 'before = \[ "hermes-agent\.service" \];'
assert_contains "$flake" 'docker load -i "\$archive"'
assert_contains "$flake" 'podman load -i "\$archive"'
assert_contains "$flake" 'Cold containerMode=true startup may pull \$image and run apt/NodeSource/Astral/uv provisioning\.'

# Bootstrap preflight must stage optional archives and warn about the remaining
# in-container package-manager dependency. It must not run for native mode.
assert_contains "$deploy" 'container_mode_preflight\(\)'
assert_contains "$deploy" 'if ! nix_option_bool_true "\$options_file" "containerMode"; then'
assert_contains "$deploy" 'data/container-images'
assert_contains "$deploy" 'containerImageArchiveDir'
assert_contains "$deploy" "find .* -name '\\*\.tar' -o -name '\\*\.tar\.gz' -o -name '\\*\.oci'"
assert_contains "$deploy" 'apt/NodeSource/Astral/uv downloads'

# Keep image archives out of git while documenting the operator workflow.
assert_contains "$repo_root/.gitignore" 'data/container-images/\*\.tar'
assert_contains "$readme" 'Do not put credentials or API keys in image archives\.'
