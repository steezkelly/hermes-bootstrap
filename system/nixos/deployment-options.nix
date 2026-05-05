# Hermes Bootstrap deployment defaults.
#
# Copy this file or edit it before deployment to customize the generated
# NixOS system without editing the main flake.
{
  # Host identity
  hostName = "hermes-node";
  nodeName = "hermes-os";

  # Interactive administrator account.
  adminUser = "hermes-admin";
  adminDescription = "Hermes administrator";

  # Hermes Agent runtime user/state.
  agentUser = "hermes";
  agentGroup = "hermes";
  stateDir = "/var/lib/hermes";
  workspaceDir = "/var/lib/hermes/workspace";

  # First-boot runtime mode.
  # false = native Nix-built service: no Docker Hub / apt / NodeSource / Astral
  #         uv downloads during the first boot of the installed machine.
  # true  = upstream OCI container mode: writable apt/npm/pip/uv tool layer, but
  #         first service start needs the image and in-container provisioning.
  containerMode = false;
  containerBackend = "docker";
  containerImage = "ubuntu:24.04";
  # Runtime directory checked on first boot when containerMode = true. Place
  # docker/podman image archives here during bootstrap to avoid registry pulls.
  containerImageArchiveDir = "/var/lib/hermes/container-images";

  # LLM defaults. Credentials live in secretsEnvFile, not in this file.
  provider = "minimax";
  model = "minimax/minimax-m2.7";

  # Local gateway. Keep this bound to localhost unless you add TLS/auth/reverse proxy hardening.
  gatewayHost = "127.0.0.1";
  gatewayPort = 8080;

  # Operational defaults.
  timeZone = "UTC";
  locale = "en_US.UTF-8";
  secretsEnvFile = "/var/lib/hermes/secrets/hermes.env";
}
