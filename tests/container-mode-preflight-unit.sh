#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Source function definitions without executing the CLI dispatcher.
# shellcheck source=/dev/null
source <(sed '/^main "\$@"$/d' "$repo_root/scripts/deploy-hermes.sh")

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

write_options() {
  local mode="$1"
  local archive_dir="$2"
  cat > "$tmp/deployment-options.nix" <<EOF
{
  containerMode = ${mode};
  containerBackend = "docker";
  containerImage = "example/hermes-tools:prewarmed";
  containerImageArchiveDir = "${archive_dir}";
}
EOF
}

# Native mode exits before creating any preload directory.
write_options false "/var/lib/hermes/container-images"
container_mode_preflight "$tmp/deployment-options.nix" "$tmp/target-native" "$tmp/bootstrap-native" >/dev/null 2>&1
[[ ! -e "$tmp/target-native/var/lib/hermes/container-images" ]]

# Explicit container mode stages supported archive files.
mkdir -p "$tmp/bootstrap/data/container-images"
printf 'not-a-real-image; copy preflight only\n' > "$tmp/bootstrap/data/container-images/example.tar"
write_options true "/var/lib/hermes/container-images"
container_mode_preflight "$tmp/deployment-options.nix" "$tmp/target" "$tmp/bootstrap" >/dev/null 2>&1
cmp "$tmp/bootstrap/data/container-images/example.tar" "$tmp/target/var/lib/hermes/container-images/example.tar"

# Custom archive directory is honored.
mkdir -p "$tmp/bootstrap-custom/data/container-images"
printf 'custom\n' > "$tmp/bootstrap-custom/data/container-images/custom.oci"
write_options true "/opt/hermes/images"
container_mode_preflight "$tmp/deployment-options.nix" "$tmp/target-custom" "$tmp/bootstrap-custom" >/dev/null 2>&1
cmp "$tmp/bootstrap-custom/data/container-images/custom.oci" "$tmp/target-custom/opt/hermes/images/custom.oci"
