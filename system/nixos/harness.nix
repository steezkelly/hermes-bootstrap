{ config, pkgs, lib, ... }:

let
  python = pkgs.python3;
  deployment = import ./deployment-options.nix;
  harnessDir = ../../scripts/harness;
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
  phase2DeliveryDryRun = pkgs.writeShellApplication {
    name = "hermes-phase2-delivery-brief-dry-run";
    runtimeInputs = [ python pkgs.coreutils ];
    text = ''
      export PYTHONPATH=${harnessDir}:''${PYTHONPATH:-}
      exec ${python}/bin/python3 ${harnessDir}/render_delivery_brief.py --base ${harnessBase} --dry-run
    '';
  };
  phase2CriticalAlertDryRun = pkgs.writeShellApplication {
    name = "hermes-phase2-critical-alert-dry-run";
    runtimeInputs = [ python pkgs.coreutils ];
    text = ''
      export PYTHONPATH=${harnessDir}:''${PYTHONPATH:-}
      exec ${python}/bin/python3 ${harnessDir}/render_critical_alerts.py --base ${harnessBase} --state-dir ${harnessBase}/delivery/state/alerts --dry-run
    '';
  };
  ackCriticalAlert = pkgs.writeShellApplication {
    name = "hermes-ack-critical-alert";
    runtimeInputs = [ python pkgs.coreutils ];
    text = ''
      export PYTHONPATH=${harnessDir}:''${PYTHONPATH:-}
      exec ${python}/bin/python3 ${harnessDir}/ack_critical_alert.py --state-dir ${harnessBase}/delivery/state/alerts "$@"
    '';
  };
  phase2DeliverySend = pkgs.writeShellApplication {
    name = "hermes-phase2-delivery-brief-send";
    runtimeInputs = [ python pkgs.coreutils ];
    text = ''
      export PYTHONPATH=${harnessDir}:''${PYTHONPATH:-}
      exec ${python}/bin/python3 ${harnessDir}/send_delivery_brief.py --base ${harnessBase} --transport ntfy --state-dir ${harnessBase}/delivery/state --once-per-date --min-interval-seconds 82800
    '';
  };
  foundryActionRoutingFixture = pkgs.writeShellApplication {
    name = "hermes-evolution-foundry-action-routing-fixture";
    runtimeInputs = [ python pkgs.coreutils ];
    text = ''
      foundry_repo=/var/lib/hermes/foundry/hermes-agent-self-evolution
      if [ ! -d "$foundry_repo/evolution" ]; then
        echo "Foundry repo missing: $foundry_repo" >&2
        exit 1
      fi
      cd "$foundry_repo"
      exec ${python}/bin/python3 -m evolution.core.action_routing_demo --out /var/lib/hermes/reports/evolution/action-routing-fixture --mode fixture --no-network --no-external-writes
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

  users.users.hermes-delivery = {
    isSystemUser = true;
    group = "hermes";
    description = "Hermes Phase 2 delivery sender";
  };

  system.activationScripts.hermesHarnessDirectories = {
    deps = [ "users" ];
    text = ''
      ${pkgs.coreutils}/bin/install -d -o hermes-harness -g hermes -m 2770 /var/lib/hermes/harness
      ${pkgs.coreutils}/bin/install -d -o hermes-harness -g hermes -m 2770 /var/lib/hermes/events
      ${pkgs.coreutils}/bin/install -d -o hermes-harness -g hermes -m 2770 /var/lib/hermes/reports
      ${pkgs.coreutils}/bin/install -d -o hermes-harness -g hermes -m 2770 /var/lib/hermes/reports/daily
      ${pkgs.coreutils}/bin/install -d -o hermes-harness -g hermes -m 2770 /var/lib/hermes/reports/evolution
      ${pkgs.coreutils}/bin/install -d -o hermes-harness -g hermes -m 2750 /var/lib/hermes/foundry
      ${pkgs.coreutils}/bin/install -d -o hermes-delivery -g hermes -m 2750 /var/lib/hermes/delivery
      ${pkgs.coreutils}/bin/install -d -o hermes-delivery -g hermes -m 2770 /var/lib/hermes/delivery/state
      ${pkgs.coreutils}/bin/install -d -o hermes-harness -g hermes -m 2770 /var/lib/hermes/delivery/state/alerts
    '';
  };

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

  systemd.services.hermes-phase2-delivery-brief-dry-run = {
    description = "Render Hermes Phase 2 delivery brief dry-run";
    after = [ "hermes-daily-local-brief.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${phase2DeliveryDryRun}/bin/hermes-phase2-delivery-brief-dry-run";
      ReadWritePaths = lib.mkForce [ ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/harness"
        "/var/lib/hermes/events"
        "/var/lib/hermes/reports"
      ];
    };
  };

  systemd.services.hermes-phase2-critical-alert-dry-run = {
    description = "Render Hermes Phase 2 critical alert candidates dry-run";
    after = [ "hermes-node-health-watchdog.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${phase2CriticalAlertDryRun}/bin/hermes-phase2-critical-alert-dry-run";
      ReadWritePaths = lib.mkForce [ "/var/lib/hermes/delivery/state/alerts" ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/harness"
        "/var/lib/hermes/events"
      ];
    };
  };

  systemd.services.hermes-phase2-delivery-brief-send = {
    description = "Send Hermes Phase 2 delivery brief manually";
    after = [ "hermes-daily-local-brief.service" ];
    serviceConfig = commonServiceConfig // {
      User = "hermes-delivery";
      ExecStart = "${phase2DeliverySend}/bin/hermes-phase2-delivery-brief-send";
      EnvironmentFile = "-/var/lib/hermes/delivery/ntfy.env";
      StateDirectory = "hermes/delivery/state";
      StateDirectoryMode = "2770";
      ReadWritePaths = lib.mkForce [ "/var/lib/hermes/delivery/state" ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/harness"
        "/var/lib/hermes/events"
        "/var/lib/hermes/reports"
        "/var/lib/hermes/delivery"
      ];
    };
  };

  systemd.services.hermes-evolution-foundry-action-routing-fixture = {
    description = "Run Agent Evolution Foundry action-routing fixture manually";
    after = [ "hermes-agent.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${foundryActionRoutingFixture}/bin/hermes-evolution-foundry-action-routing-fixture";
      ReadWritePaths = lib.mkForce [ "/var/lib/hermes/reports/evolution" ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/foundry"
      ];
      InaccessiblePaths = lib.mkForce [ "-/var/lib/hermes/secrets" ];
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

  systemd.timers.hermes-phase2-delivery-brief-send = lib.mkIf deployment.phase2DeliveryTimerEnabled {
    description = "Send Hermes Phase 2 delivery brief on the configured schedule";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = deployment.phase2DeliveryTimerCalendar;
      AccuracySec = "5min";
      Persistent = true;
      Unit = "hermes-phase2-delivery-brief-send.service";
    };
  };
}
