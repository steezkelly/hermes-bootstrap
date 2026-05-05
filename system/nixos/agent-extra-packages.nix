# Extra packages available to the Hermes Agent service and interactive shell.
# Kept in a separate file so CI can evaluate package names without forcing the
# upstream hermes-agent package derivation.
{ pkgs }:
[
  # Build
  pkgs.gcc pkgs.gnumake pkgs.cmake pkgs.pkg-config
  # Python
  pkgs.python3 pkgs.python3Packages.pip pkgs.python3Packages.virtualenv
  # Node
  pkgs.nodejs
  # Data processing
  pkgs.jq pkgs.yq pkgs.ripgrep pkgs.fd pkgs.fzf
  # Core utils
  pkgs.coreutils pkgs.findutils pkgs.gawk pkgs.gnused pkgs.gnutar
  pkgs.gzip pkgs.xz pkgs.zip pkgs.unzip pkgs.p7zip
  # Network
  pkgs.openssh pkgs.curl pkgs.wget pkgs.rsync
  # Monitoring
  pkgs.htop pkgs.iotop pkgs.strace pkgs.lsof
  # VCS
  pkgs.git pkgs.git-lfs
  # Containers
  pkgs.docker pkgs.docker-compose
  # Media tools
  pkgs.ffmpeg pkgs.imagemagick
  # Security
  pkgs.pass pkgs.gnupg
  # Cloud sync
  pkgs.rclone
]
