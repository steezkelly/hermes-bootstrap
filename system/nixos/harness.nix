{ config, pkgs, lib, ... }:

let
  python = pkgs.python3;
  harnessDir = if builtins.pathExists ./harness-scripts then ./harness-scripts else ../../scripts/harness;
  harnessBase = "/var/lib/hermes";
  watchdog = pkgs.writeShellApplication {
    name = "hermes-node-health-watchdog";
    runtimeInputs = [ python pkgs.coreutils pkgs.iproute2 pkgs.procps pkgs.systemd ];
    text = ''
      export PYTHONPATH=${harnessDir}:''${PYTHONPATH:-}
      exec ${python}/bin/python3 ${harnessDir}/node_health_watchdog.py --base ${harnessBase}
    '';
  };
  dailyReport = pkgs.writeShellApplication {
    name = "hermes-daily-local-brief";
    runtimeInputs = [ python pkgs.coreutils ];
    text = ''
      export PYTHONPATH=${harnessDir}:''${PYTHONPATH:-}
      exec ${python}/bin/python3 ${harnessDir}/render_daily_report.py --base ${harnessBase}
    '';
  };
  commonServiceConfig = {
    User = "hermes-harness";
    Group = "hermes";
    UMask = "0007";
    Type = "oneshot";
    TimeoutStartSec = "30s";
    ProtectSystem = "strict";
    ProtectHome = true;
    ReadWritePaths = [
      "/var/lib/hermes/harness"
      "/var/lib/hermes/events"
      "/var/lib/hermes/reports"
    ];
    ReadOnlyPaths = [ "/var/lib/hermes/.hermes" ];
    InaccessiblePaths = [ "-/var/lib/hermes/secrets" ];
    NoNewPrivileges = true;
    PrivateTmp = true;
    RestrictSUIDSGID = true;
    LockPersonality = true;
    CapabilityBoundingSet = "";
  };
in
{
  users.users.hermes-harness = {
    isSystemUser = true;
    group = "hermes";
    description = "Hermes node local observability harness";
  };

  systemd.tmpfiles.rules = [
    "d /var/lib/hermes/harness 2770 hermes-harness hermes -"
    "d /var/lib/hermes/events 2770 hermes-harness hermes -"
    "d /var/lib/hermes/reports 2770 hermes-harness hermes -"
    "d /var/lib/hermes/reports/daily 2770 hermes-harness hermes -"
  ];

  systemd.services.hermes-node-health-watchdog = {
    description = "Hermes node Phase 1 local health watchdog";
    after = [ "NetworkManager.service" "hermes-agent.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${watchdog}/bin/hermes-node-health-watchdog";
    };
  };

  systemd.timers.hermes-node-health-watchdog = {
    description = "Run Hermes node health watchdog every 30 minutes";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "5min";
      OnUnitActiveSec = "30min";
      AccuracySec = "1min";
      Unit = "hermes-node-health-watchdog.service";
    };
  };

  systemd.services.hermes-daily-local-brief = {
    description = "Render Hermes node deterministic daily local brief";
    after = [ "hermes-node-health-watchdog.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${dailyReport}/bin/hermes-daily-local-brief";
    };
  };

  systemd.timers.hermes-daily-local-brief = {
    description = "Render Hermes node deterministic daily local brief at 06:00 UTC";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "*-*-* 06:00:00";
      AccuracySec = "5min";
      Persistent = true;
      Unit = "hermes-daily-local-brief.service";
    };
  };
}
