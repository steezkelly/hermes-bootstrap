{ config, pkgs, lib, ... }:

let
  python = pkgs.python3;
  deployment = import ./deployment-options.nix;
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
  provisionFoundryCheckout = pkgs.writeShellApplication {
    name = "hermes-provision-foundry-checkout";
    runtimeInputs = [ python pkgs.coreutils pkgs.rsync pkgs.gnutar ];
    text = ''
      target=/var/lib/hermes/foundry/hermes-agent-self-evolution
      if [ -d "$target/evolution" ]; then
        echo "Foundry checkout already present: $target" >&2
        exit 0
      fi

      # Bootstrap accepts a local source path via env var or fixed deploy-time
      # copy.  No network clone, no GitHub credential, no external writes.
      source="''${FOUNDRY_CHECKOUT_SOURCE:-}"
      if [ -z "$source" ]; then
        echo "FOUNDRY_CHECKOUT_SOURCE is not set.  Set it to a local" >&2
        echo "Foundry repo path or tarball, e.g.:" >&2
        echo "  FOUNDRY_CHECKOUT_SOURCE=/home/admin/steezkelly-hermes-agent-self-evolution" >&2
        echo "Provisioning nothing and exiting 1." >&2
        exit 1
      fi

      if [ -d "$source/evolution" ]; then
        ${pkgs.coreutils}/bin/mkdir -p "$(dirname "$target")"
        ${pkgs.rsync}/bin/rsync -a --delete "$source/" "$target/"
        echo "Provisioned Foundry from directory: $source" >&2
        exit 0
      fi

      if [ -f "$source" ]; then
        ${pkgs.coreutils}/bin/mkdir -p "$(dirname "$target")"
        ${pkgs.gnutar}/bin/tar -x -f "$source" -C "$(dirname "$target")"
        echo "Provisioned Foundry from archive: $source" >&2
        exit 0
      fi

      echo "FOUNDRY_CHECKOUT_SOURCE does not appear to be a Foundry checkout:" >&2
      echo "  $source" >&2
      exit 1
    '';
  };
  validateFoundryActionRoutingFixture = pkgs.writeShellApplication {
    name = "hermes-validate-foundry-action-routing-fixture";
    runtimeInputs = [ python pkgs.coreutils ];
    text = ''
      exec ${python}/bin/python3 ${harnessDir}/validate_foundry_action_routing_fixture.py /var/lib/hermes/reports/evolution/action-routing-fixture
    '';
  };
  validateFoundrySessionImportFixture = pkgs.writeShellApplication {
    name = "hermes-validate-foundry-session-import-fixture";
    runtimeInputs = [ python pkgs.coreutils ];
    text = ''
      exec ${python}/bin/python3 ${harnessDir}/validate_foundry_session_import_fixture.py /var/lib/hermes/reports/evolution/session-import-fixture
    '';
  };
  foundrySessionImportFixture = pkgs.writeShellApplication {
    name = "hermes-evolution-foundry-session-import-fixture";
    runtimeInputs = [ python pkgs.coreutils ];
    text = ''
      foundry_repo=/var/lib/hermes/foundry/hermes-agent-self-evolution
      if [ ! -d "$foundry_repo/evolution" ]; then
        echo "Foundry repo missing: $foundry_repo" >&2
        exit 1
      fi
      cd "$foundry_repo"
      exec ${python}/bin/python3 -m evolution.core.session_import_demo --out /var/lib/hermes/reports/evolution/session-import-fixture --mode fixture --no-network --no-external-writes
    '';
  };
  foundryToolUnderuseFixture = pkgs.writeShellApplication {
    name = "hermes-evolution-foundry-tool-underuse-fixture";
    runtimeInputs = [ python pkgs.coreutils ];
    text = ''
      foundry_repo=/var/lib/hermes/foundry/hermes-agent-self-evolution
      if [ ! -d "$foundry_repo/evolution" ]; then
        echo "Foundry repo missing: $foundry_repo" >&2
        exit 1
      fi
      cd "$foundry_repo"
      exec ${python}/bin/python3 -m evolution.core.tool_underuse_demo --out /var/lib/hermes/reports/evolution/tool-underuse-fixture --mode fixture --no-network --no-external-writes
    '';
  };
  validateFoundryToolUnderuseFixture = pkgs.writeShellApplication {
    name = "hermes-validate-foundry-tool-underuse-fixture";
    runtimeInputs = [ python pkgs.coreutils ];
    text = ''
      exec ${python}/bin/python3 ${harnessDir}/validate_foundry_tool_underuse_fixture.py /var/lib/hermes/reports/evolution/tool-underuse-fixture
    '';
  };
  foundrySkillDriftFixture = pkgs.writeShellApplication {
    name = "hermes-evolution-foundry-skill-drift-fixture";
    runtimeInputs = [ python pkgs.coreutils ];
    text = ''
      foundry_repo=/var/lib/hermes/foundry/hermes-agent-self-evolution
      if [ ! -d "$foundry_repo/evolution" ]; then
        echo "Foundry repo missing: $foundry_repo" >&2
        exit 1
      fi
      cd "$foundry_repo"
      exec ${python}/bin/python3 -m evolution.core.skill_drift_demo --out /var/lib/hermes/reports/evolution/skill-drift-fixture --mode fixture --no-network --no-external-writes
    '';
  };
  validateFoundrySkillDriftFixture = pkgs.writeShellApplication {
    name = "hermes-validate-foundry-skill-drift-fixture";
    runtimeInputs = [ python pkgs.coreutils ];
    text = ''
      exec ${python}/bin/python3 ${harnessDir}/validate_foundry_skill_drift_fixture.py /var/lib/hermes/reports/evolution/skill-drift-fixture
    '';
  };
  promoteFoundryFixture = pkgs.writeShellApplication {
    name = "hermes-promote-foundry-fixture";
    runtimeInputs = [ python pkgs.coreutils ];
    text = ''
      exec ${python}/bin/python3 ${harnessDir}/promote_foundry_fixture.py "$@"
    '';
  };
  foundryRealTraceIngestion = pkgs.writeShellApplication {
    name = "hermes-evolution-foundry-real-trace-ingestion";
    runtimeInputs = [ python pkgs.coreutils ];
    text = ''
      foundry_repo=/var/lib/hermes/foundry/hermes-agent-self-evolution
      if [ ! -d "$foundry_repo/evolution" ]; then
        echo "Foundry repo missing: $foundry_repo" >&2
        exit 1
      fi
      trace="''${REAL_TRACE_SOURCE:-}"
      if [ -z "$trace" ]; then
        echo "REAL_TRACE_SOURCE is not set. Pass the path to an exported Hermes session JSONL file." >&2
        echo "Example: REAL_TRACE_SOURCE=/var/lib/hermes/.hermes/sessions/session_export.jsonl" >&2
        exit 1
      fi
      if [ ! -f "$trace" ]; then
        echo "Trace file not found: $trace" >&2
        exit 1
      fi
      cd "$foundry_repo"
      exec ${python}/bin/python3 -m evolution.core.real_trace_ingestion --trace "$trace" --out /var/lib/hermes/reports/evolution/real-trace-ingestion --mode real_trace --no-network --no-external-writes
    '';
  };
  validateFoundryRealTraceIngestion = pkgs.writeShellApplication {
    name = "hermes-validate-foundry-real-trace-ingestion";
    runtimeInputs = [ python pkgs.coreutils ];
    text = ''
      exec ${python}/bin/python3 ${harnessDir}/validate_foundry_real_trace_ingestion.py /var/lib/hermes/reports/evolution/real-trace-ingestion
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

  environment.systemPackages = [ ackCriticalAlert ];

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

  systemd.services.hermes-provision-foundry-checkout = {
    description = "Provision Foundry checkout for manual appliance wrappers";
    after = [ "hermes-agent.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${provisionFoundryCheckout}/bin/hermes-provision-foundry-checkout";
      ReadWritePaths = lib.mkForce [ "/var/lib/hermes/foundry" ];
      ReadOnlyPaths = lib.mkForce [ ];
    };
  };

  systemd.services.hermes-validate-foundry-action-routing-fixture = {
    description = "Validate Foundry action-routing fixture output boundaries";
    after = [ "hermes-evolution-foundry-action-routing-fixture.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${validateFoundryActionRoutingFixture}/bin/hermes-validate-foundry-action-routing-fixture";
      ReadWritePaths = lib.mkForce [ ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/reports/evolution"
      ];
    };
  };

  systemd.services.hermes-evolution-foundry-session-import-fixture = {
    description = "Run Agent Evolution Foundry session-import fixture manually";
    after = [ "hermes-agent.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${foundrySessionImportFixture}/bin/hermes-evolution-foundry-session-import-fixture";
      ReadWritePaths = lib.mkForce [ "/var/lib/hermes/reports/evolution" ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/foundry"
      ];
      InaccessiblePaths = lib.mkForce [ "-/var/lib/hermes/secrets" ];
    };
  };

  systemd.services.hermes-validate-foundry-session-import-fixture = {
    description = "Validate Foundry session-import fixture output boundaries";
    after = [ "hermes-evolution-foundry-session-import-fixture.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${validateFoundrySessionImportFixture}/bin/hermes-validate-foundry-session-import-fixture";
      ReadWritePaths = lib.mkForce [ ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/reports/evolution"
      ];
    };
  };

  systemd.services.hermes-evolution-foundry-tool-underuse-fixture = {
    description = "Run Agent Evolution Foundry tool-underuse fixture manually";
    after = [ "hermes-agent.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${foundryToolUnderuseFixture}/bin/hermes-evolution-foundry-tool-underuse-fixture";
      ReadWritePaths = lib.mkForce [ "/var/lib/hermes/reports/evolution" ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/foundry"
      ];
      InaccessiblePaths = lib.mkForce [ "-/var/lib/hermes/secrets" ];
    };
  };

  systemd.services.hermes-validate-foundry-tool-underuse-fixture = {
    description = "Validate Foundry tool-underuse fixture output boundaries";
    after = [ "hermes-evolution-foundry-tool-underuse-fixture.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${validateFoundryToolUnderuseFixture}/bin/hermes-validate-foundry-tool-underuse-fixture";
      ReadWritePaths = lib.mkForce [ ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/reports/evolution"
      ];
    };
  };

  systemd.services.hermes-evolution-foundry-skill-drift-fixture = {
    description = "Run Agent Evolution Foundry skill-drift fixture manually";
    after = [ "hermes-agent.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${foundrySkillDriftFixture}/bin/hermes-evolution-foundry-skill-drift-fixture";
      ReadWritePaths = lib.mkForce [ "/var/lib/hermes/reports/evolution" ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/foundry"
      ];
      InaccessiblePaths = lib.mkForce [ "-/var/lib/hermes/secrets" ];
    };
  };

  systemd.services.hermes-validate-foundry-skill-drift-fixture = {
    description = "Validate Foundry skill-drift fixture output boundaries";
    after = [ "hermes-evolution-foundry-skill-drift-fixture.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${validateFoundrySkillDriftFixture}/bin/hermes-validate-foundry-skill-drift-fixture";
      ReadWritePaths = lib.mkForce [ ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/reports/evolution"
      ];
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

  systemd.services.hermes-evolution-foundry-real-trace-ingestion = {
    description = "Ingest a real Hermes session trace through Foundry detectors manually";
    after = [ "hermes-agent.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${foundryRealTraceIngestion}/bin/hermes-evolution-foundry-real-trace-ingestion";
      ReadWritePaths = lib.mkForce [ "/var/lib/hermes/reports/evolution" ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/foundry"
        "/var/lib/hermes/.hermes/sessions"
      ];
      InaccessiblePaths = lib.mkForce [ "-/var/lib/hermes/secrets" ];
    };
  };

  systemd.services.hermes-validate-foundry-real-trace-ingestion = {
    description = "Validate Foundry real-trace ingestion output boundaries";
    after = [ "hermes-evolution-foundry-real-trace-ingestion.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${validateFoundryRealTraceIngestion}/bin/hermes-validate-foundry-real-trace-ingestion";
      ReadWritePaths = lib.mkForce [ ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/reports/evolution"
      ];
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

  # Weekly dry-run of the full evolution pipeline: run all fixtures,
  # then validate all boundaries. Default disabled. No external writes.
  systemd.timers.hermes-evolution-foundry-weekly-dry-run = lib.mkIf deployment.evolutionFoundryTimerEnabled {
    description = "Weekly dry-run of evolution Foundry pipeline";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = deployment.evolutionFoundryTimerCalendar;
      AccuracySec = "30min";
      Persistent = true;
      Unit = "hermes-evolution-foundry-action-routing-fixture.service";
    };
  };
}
