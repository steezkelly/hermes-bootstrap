{ config, pkgs, lib, ... }:

let
  python = pkgs.python3;
  pythonFoundry = pkgs.python3.withPackages (ps: [ ps.numpy ps.click ps.scikitlearn ps.pytest ]);
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
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      foundry_repo=/var/lib/hermes/foundry/hermes-agent-self-evolution
      if [ ! -d "$foundry_repo/evolution" ]; then
        echo "Foundry repo missing: $foundry_repo" >&2
        exit 1
      fi
      cd "$foundry_repo"
      exec ${pythonFoundry}/bin/python3 -m evolution.core.action_routing_demo --out /var/lib/hermes/reports/evolution/action-routing-fixture --mode fixture --no-network --no-external-writes
    '';
  };
  provisionFoundryCheckout = pkgs.writeShellApplication {
    name = "hermes-provision-foundry-checkout";
    runtimeInputs = [ pythonFoundry pkgs.coreutils pkgs.rsync pkgs.gnutar ];
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
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      exec ${pythonFoundry}/bin/python3 ${harnessDir}/validate_foundry_action_routing_fixture.py /var/lib/hermes/reports/evolution/action-routing-fixture
    '';
  };
  validateFoundrySessionImportFixture = pkgs.writeShellApplication {
    name = "hermes-validate-foundry-session-import-fixture";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      exec ${pythonFoundry}/bin/python3 ${harnessDir}/validate_foundry_session_import_fixture.py /var/lib/hermes/reports/evolution/session-import-fixture
    '';
  };
  foundrySessionImportFixture = pkgs.writeShellApplication {
    name = "hermes-evolution-foundry-session-import-fixture";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      foundry_repo=/var/lib/hermes/foundry/hermes-agent-self-evolution
      if [ ! -d "$foundry_repo/evolution" ]; then
        echo "Foundry repo missing: $foundry_repo" >&2
        exit 1
      fi
      cd "$foundry_repo"
      exec ${pythonFoundry}/bin/python3 -m evolution.core.session_import_demo --out /var/lib/hermes/reports/evolution/session-import-fixture --mode fixture --no-network --no-external-writes
    '';
  };
  foundryToolUnderuseFixture = pkgs.writeShellApplication {
    name = "hermes-evolution-foundry-tool-underuse-fixture";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      foundry_repo=/var/lib/hermes/foundry/hermes-agent-self-evolution
      if [ ! -d "$foundry_repo/evolution" ]; then
        echo "Foundry repo missing: $foundry_repo" >&2
        exit 1
      fi
      cd "$foundry_repo"
      exec ${pythonFoundry}/bin/python3 -m evolution.core.tool_underuse_demo --out /var/lib/hermes/reports/evolution/tool-underuse-fixture --mode fixture --no-network --no-external-writes
    '';
  };
  validateFoundryToolUnderuseFixture = pkgs.writeShellApplication {
    name = "hermes-validate-foundry-tool-underuse-fixture";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      exec ${pythonFoundry}/bin/python3 ${harnessDir}/validate_foundry_tool_underuse_fixture.py /var/lib/hermes/reports/evolution/tool-underuse-fixture
    '';
  };
  foundrySkillDriftFixture = pkgs.writeShellApplication {
    name = "hermes-evolution-foundry-skill-drift-fixture";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      foundry_repo=/var/lib/hermes/foundry/hermes-agent-self-evolution
      if [ ! -d "$foundry_repo/evolution" ]; then
        echo "Foundry repo missing: $foundry_repo" >&2
        exit 1
      fi
      cd "$foundry_repo"
      exec ${pythonFoundry}/bin/python3 -m evolution.core.skill_drift_demo --out /var/lib/hermes/reports/evolution/skill-drift-fixture --mode fixture --no-network --no-external-writes
    '';
  };
  validateFoundrySkillDriftFixture = pkgs.writeShellApplication {
    name = "hermes-validate-foundry-skill-drift-fixture";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      exec ${pythonFoundry}/bin/python3 ${harnessDir}/validate_foundry_skill_drift_fixture.py /var/lib/hermes/reports/evolution/skill-drift-fixture
    '';
  };
  promoteFoundryFixture = pkgs.writeShellApplication {
    name = "hermes-promote-foundry-fixture";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      exec ${pythonFoundry}/bin/python3 ${harnessDir}/promote_foundry_fixture.py "$@"
    '';
  };
  foundryRealTraceIngestion = pkgs.writeShellApplication {
    name = "hermes-evolution-foundry-real-trace-ingestion";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
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
      exec ${pythonFoundry}/bin/python3 -m evolution.core.real_trace_ingestion --trace "$trace" --out /var/lib/hermes/reports/evolution/real-trace-ingestion --mode real_trace --no-network --no-external-writes
    '';
  };
  validateFoundryRealTraceIngestion = pkgs.writeShellApplication {
    name = "hermes-validate-foundry-real-trace-ingestion";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      exec ${pythonFoundry}/bin/python3 ${harnessDir}/validate_foundry_real_trace_ingestion.py /var/lib/hermes/reports/evolution/real-trace-ingestion
    '';
  };
  foundryAttentionRouterBridge = pkgs.writeShellApplication {
    name = "hermes-evolution-foundry-attention-router-bridge";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      foundry_repo=/var/lib/hermes/foundry/hermes-agent-self-evolution
      if [ ! -d "$foundry_repo/evolution" ]; then
        echo "Foundry repo missing: $foundry_repo" >&2
        exit 1
      fi
      input=/var/lib/hermes/reports/evolution/real-trace-ingestion
      if [ ! -f "$input/run_report.json" ]; then
        echo "Real-trace ingestion report missing: $input/run_report.json" >&2
        exit 1
      fi
      cd "$foundry_repo"
      exec ${pythonFoundry}/bin/python3 -m evolution.core.attention_router_bridge --input /var/lib/hermes/reports/evolution/real-trace-ingestion --out /var/lib/hermes/reports/evolution/attention-router-bridge --mode attention_router_bridge --no-network --no-external-writes
    '';
  };
  validateFoundryAttentionRouterBridge = pkgs.writeShellApplication {
    name = "hermes-validate-foundry-attention-router-bridge";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      exec ${pythonFoundry}/bin/python3 ${harnessDir}/validate_foundry_attention_router_bridge.py /var/lib/hermes/reports/evolution/attention-router-bridge
    '';
  };
  foundryPipelineRunner = pkgs.writeShellApplication {
    name = "hermes-evolution-foundry-pipeline-runner";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      foundry_repo=/var/lib/hermes/foundry/hermes-agent-self-evolution
      if [ ! -d "$foundry_repo/evolution" ]; then
        echo "Foundry repo missing: $foundry_repo" >&2
        exit 1
      fi

      mode="''${FOUNDRY_PIPELINE_MODE:-fixture}"
      trace="''${FOUNDRY_PIPELINE_TRACE:-}"
      case "$mode" in
        fixture|real_trace) ;;
        *)
          echo "Unsupported FOUNDRY_PIPELINE_MODE: $mode (expected fixture|real_trace)" >&2
          exit 1
          ;;
      esac

      args=(
        --out /var/lib/hermes/reports/evolution/pipeline-runner
        --mode "$mode"
        --no-network
        --no-external-writes
      )
      if [ "$mode" = "real_trace" ]; then
        if [ -z "$trace" ]; then
          echo "FOUNDRY_PIPELINE_TRACE is required when FOUNDRY_PIPELINE_MODE=real_trace" >&2
          exit 1
        fi
        if [ ! -f "$trace" ]; then
          echo "Trace file not found: $trace" >&2
          exit 1
        fi
        args+=(--trace "$trace")
      fi

      cd "$foundry_repo"
      exec ${pythonFoundry}/bin/python3 -m evolution.core.pipeline_runner "''${args[@]}"
    '';
  };
  validateFoundryPipelineRunner = pkgs.writeShellApplication {
    name = "hermes-validate-foundry-pipeline-runner";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      exec ${pythonFoundry}/bin/python3 ${harnessDir}/validate_foundry_pipeline_runner.py /var/lib/hermes/reports/evolution/pipeline-runner
    '';
  };
  sessionEndIngest = pkgs.writeShellApplication {
    name = "hermes-session-end-ingest";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      export HERMES_HOME=/var/lib/hermes/.hermes
      export HOME=/var/lib/hermes
      exec ${pythonFoundry}/bin/python3 ${harnessDir}/export_and_ingest_last_session.py \
        --hermes-bin /run/current-system/sw/bin/hermes \
        --python-bin ${pythonFoundry}/bin/python3 \
        --foundry-repo /var/lib/hermes/foundry/hermes-agent-self-evolution \
        --out /var/lib/hermes/reports/evolution/session-end-ingest
    '';
  };
  foundryTraceOptimizer = pkgs.writeShellApplication {
    name = "hermes-evolution-foundry-trace-optimizer";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      exec ${pythonFoundry}/bin/python3 ${harnessDir}/../repos/steezkelly-hermes-agent-self-evolution/evolution/core/trace_optimizer.py \
        --eval-examples /var/lib/hermes/reports/evolution/session-end-ingest/real_trace_ingestion/eval_examples.json \
        --out /var/lib/hermes/reports/evolution/trace-optimizer \
        --mode optimizer \
        --no-network --no-external-writes
    '';
  };
  validateFoundryTraceOptimizer = pkgs.writeShellApplication {
    name = "hermes-validate-foundry-trace-optimizer";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      exec ${pythonFoundry}/bin/python3 ${harnessDir}/validate_foundry_trace_optimizer.py /var/lib/hermes/reports/evolution/trace-optimizer
    '';
  };
  foundryGepaBridge = pkgs.writeShellApplication {
    name = "hermes-evolution-foundry-gepa-bridge";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      exec ${pythonFoundry}/bin/python3 ${harnessDir}/../repos/steezkelly-hermes-agent-self-evolution/evolution/core/gepa_trace_bridge.py \
        --candidate-artifacts /var/lib/hermes/reports/evolution/trace-optimizer/candidate_artifacts.json \
        --out /var/lib/hermes/reports/evolution/gepa-bridge \
        --no-network --no-external-writes
    '';
  };
  validateFoundryGepaBridge = pkgs.writeShellApplication {
    name = "hermes-validate-foundry-gepa-bridge";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      exec ${pythonFoundry}/bin/python3 ${harnessDir}/validate_foundry_gepa_bridge.py /var/lib/hermes/reports/evolution/gepa-bridge
    '';
  };
  foundryObservatoryHealth = pkgs.writeShellApplication {
    name = "hermes-evolution-foundry-observatory-health";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      exec ${pythonFoundry}/bin/python3 ${harnessDir}/run_foundry_observatory_health.py \
        --foundry-repo /var/lib/hermes/foundry/hermes-agent-self-evolution \
        --python-bin ${pythonFoundry}/bin/python3 \
        --db-path /var/lib/hermes/reports/evolution/observatory/judge_audit_log.db \
        --output /var/lib/hermes/reports/evolution/observatory/health.json
    '';
  };
  validateFoundryObservatoryHealth = pkgs.writeShellApplication {
    name = "hermes-validate-foundry-observatory-health";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      exec ${pythonFoundry}/bin/python3 ${harnessDir}/validate_foundry_observatory_health.py \
        --report /var/lib/hermes/reports/evolution/observatory/health.json
    '';
  };
  foundryContentEvolution = pkgs.writeShellApplication {
    name = "hermes-evolution-foundry-content-evolution";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      foundry_repo=/var/lib/hermes/foundry/hermes-agent-self-evolution
      if [ ! -f "$foundry_repo/evolution/skills/evolve_content.py" ]; then
        echo "Foundry content evolution CLI missing: $foundry_repo/evolution/skills/evolve_content.py" >&2
        exit 1
      fi

      skill="''${FOUNDRY_CONTENT_SKILL:-}"
      if [ -z "$skill" ]; then
        echo "FOUNDRY_CONTENT_SKILL is required (example: github-code-review)" >&2
        exit 1
      fi

      eval_source="''${FOUNDRY_CONTENT_EVAL_SOURCE:-synthetic}"
      case "$eval_source" in
        synthetic|golden|sessiondb) ;;
        *)
          echo "Unsupported FOUNDRY_CONTENT_EVAL_SOURCE: $eval_source (expected synthetic|golden|sessiondb)" >&2
          exit 1
          ;;
      esac

      dataset_path="''${FOUNDRY_CONTENT_DATASET_PATH:-}"
      evaluator_model="''${FOUNDRY_CONTENT_EVALUATOR_MODEL:-minimax/minimax-m2.7}"
      rewrite_model="''${FOUNDRY_CONTENT_REWRITE_MODEL:-minimax/minimax-m2.7}"
      rewrite_budget="''${FOUNDRY_CONTENT_REWRITE_BUDGET:-3}"
      weak_fraction="''${FOUNDRY_CONTENT_WEAK_FRACTION:-0.3333333333333333}"
      hermes_repo="''${FOUNDRY_CONTENT_HERMES_REPO:-/var/lib/hermes/.hermes}"

      export HOME=/var/lib/hermes
      export HERMES_HOME=/var/lib/hermes/.hermes
      export HERMES_AGENT_REPO="$hermes_repo"

      args=(
        --foundry-repo /var/lib/hermes/foundry/hermes-agent-self-evolution
        --python-bin ${pythonFoundry}/bin/python3
        --skill "$skill"
        --output-dir /var/lib/hermes/reports/evolution/content-evolution
        --eval-source "$eval_source"
        --evaluator-model "$evaluator_model"
        --rewrite-model "$rewrite_model"
        --rewrite-budget "$rewrite_budget"
        --weak-fraction "$weak_fraction"
        --hermes-repo "$hermes_repo"
      )
      if [ -n "$dataset_path" ]; then
        args+=(--dataset-path "$dataset_path")
      fi
      if [ "''${FOUNDRY_CONTENT_DRY_RUN:-}" = "1" ]; then
        args+=(--dry-run)
      fi

      exec ${pythonFoundry}/bin/python3 ${harnessDir}/run_foundry_content_evolution.py "''${args[@]}"
    '';
  };
  validateFoundryContentEvolution = pkgs.writeShellApplication {
    name = "hermes-validate-foundry-content-evolution";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      exec ${pythonFoundry}/bin/python3 ${harnessDir}/validate_foundry_content_evolution.py \
        /var/lib/hermes/reports/evolution/content-evolution
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
      "/var/lib/hermes/cache"
    ];
    ReadOnlyPaths = [ "/var/lib/hermes/.hermes" ];
    InaccessiblePaths = [ "-/var/lib/hermes/secrets" ];
    NoNewPrivileges = true;
    PrivateTmp = true;
    RestrictSUIDSGID = true;
    LockPersonality = true;
    CapabilityBoundingSet = "";
  };

  autonomousEvolutionChain = pkgs.writeShellApplication {
    name = "hermes-autonomous-evolution-chain";
    runtimeInputs = [ pythonFoundry pkgs.coreutils ];
    text = ''
      # Make system libs available to pip-installed native wheels (dspy -> numpy/tokenizers)
      export LD_LIBRARY_PATH=''${NIX_LD_LIBRARY_PATH:-}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
      chain_runner=/var/lib/hermes/harness/autonomous/chain_runner.py
      if [ ! -f "$chain_runner" ]; then
        echo "Autonomous chain runner not found: $chain_runner" >&2
        exit 1
      fi
      exec ${pythonFoundry}/bin/python3 "$chain_runner"
    '';
  };
in
{
  # Enable nix-ld so pip-installed native wheels (dspy/numpy/tokenizers) can find
  # libstdc++, libz, etc. at runtime via LD_LIBRARY_PATH.
  programs.nix-ld.enable = true;

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
      ${pkgs.coreutils}/bin/install -d -o hermes-harness -g hermes -m 2770 /var/lib/hermes/harness/autonomous
      ${pkgs.coreutils}/bin/install -o hermes-harness -g hermes -m 0755 ${harnessDir}/autonomous/chain_runner.py /var/lib/hermes/harness/autonomous/chain_runner.py
      ${pkgs.coreutils}/bin/install -d -o hermes-harness -g hermes -m 2770 /var/lib/hermes/events
      ${pkgs.coreutils}/bin/install -d -o hermes-harness -g hermes -m 2770 /var/lib/hermes/reports
      ${pkgs.coreutils}/bin/install -d -o hermes-harness -g hermes -m 2770 /var/lib/hermes/reports/daily
      ${pkgs.coreutils}/bin/install -d -o hermes-harness -g hermes -m 2770 /var/lib/hermes/reports/evolution
      ${pkgs.coreutils}/bin/install -d -o hermes-harness -g hermes -m 2770 /var/lib/hermes/reports/evolution/attention-router-bridge
      ${pkgs.coreutils}/bin/install -d -o hermes-harness -g hermes -m 2770 /var/lib/hermes/reports/evolution/pipeline-runner
      ${pkgs.coreutils}/bin/install -d -o hermes-harness -g hermes -m 2770 /var/lib/hermes/reports/evolution/content-evolution
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

  systemd.services.hermes-evolution-foundry-attention-router-bridge = {
    description = "Convert Foundry real-trace detections into action-router items manually";
    after = [ "hermes-evolution-foundry-real-trace-ingestion.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${foundryAttentionRouterBridge}/bin/hermes-evolution-foundry-attention-router-bridge";
      ReadWritePaths = lib.mkForce [ "/var/lib/hermes/reports/evolution/attention-router-bridge" ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/foundry"
        "/var/lib/hermes/reports/evolution/real-trace-ingestion"
      ];
      InaccessiblePaths = lib.mkForce [ "-/var/lib/hermes/secrets" ];
    };
  };

  systemd.services.hermes-validate-foundry-attention-router-bridge = {
    description = "Validate Foundry attention-router bridge output boundaries";
    after = [ "hermes-evolution-foundry-attention-router-bridge.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${validateFoundryAttentionRouterBridge}/bin/hermes-validate-foundry-attention-router-bridge";
      ReadWritePaths = lib.mkForce [ ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/reports/evolution/attention-router-bridge"
      ];
    };
  };

  systemd.services.hermes-evolution-foundry-pipeline-runner = {
    description = "Run the Foundry fixture or real-trace pipeline runner manually";
    after = [ "hermes-agent.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${foundryPipelineRunner}/bin/hermes-evolution-foundry-pipeline-runner";
      ReadWritePaths = lib.mkForce [ "/var/lib/hermes/reports/evolution/pipeline-runner" ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/foundry"
        "/var/lib/hermes/.hermes/sessions"
      ];
      InaccessiblePaths = lib.mkForce [
        "-/var/lib/hermes/secrets"
        "-/var/lib/hermes/.hermes/.env"
      ];
    };
  };

  systemd.services.hermes-validate-foundry-pipeline-runner = {
    description = "Validate Foundry pipeline-runner output boundaries";
    after = [ "hermes-evolution-foundry-pipeline-runner.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${validateFoundryPipelineRunner}/bin/hermes-validate-foundry-pipeline-runner";
      ReadWritePaths = lib.mkForce [ ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/reports/evolution/pipeline-runner"
      ];
    };
  };

  systemd.services.hermes-session-end-ingest = {
    description = "Export latest Hermes session and ingest it through Foundry manually";
    after = [ "hermes-agent.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${sessionEndIngest}/bin/hermes-session-end-ingest";
      ReadWritePaths = lib.mkForce [ "/var/lib/hermes/reports/evolution" ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/foundry"
        "/var/lib/hermes/.hermes/sessions"
      ];
      InaccessiblePaths = lib.mkForce [
        "-/var/lib/hermes/secrets"
        "-/var/lib/hermes/.hermes/.env"
      ];
    };
  };

  systemd.services.hermes-evolution-foundry-trace-optimizer = {
    description = "Run deterministic trace optimizer over ingestion eval examples";
    after = [ "hermes-session-end-ingest.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${foundryTraceOptimizer}/bin/hermes-evolution-foundry-trace-optimizer";
      ReadWritePaths = lib.mkForce [ "/var/lib/hermes/reports/evolution/trace-optimizer" ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/foundry"
        "/var/lib/hermes/reports/evolution/session-end-ingest"
      ];
      InaccessiblePaths = lib.mkForce [
        "-/var/lib/hermes/secrets"
        "-/var/lib/hermes/.hermes/.env"
      ];
    };
  };

  systemd.services.hermes-validate-foundry-trace-optimizer = {
    description = "Validate Foundry trace-optimizer output boundaries";
    after = [ "hermes-evolution-foundry-trace-optimizer.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${validateFoundryTraceOptimizer}/bin/hermes-validate-foundry-trace-optimizer";
      ReadWritePaths = lib.mkForce [ ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/reports/evolution/trace-optimizer"
      ];
    };
  };

  systemd.services.hermes-evolution-foundry-gepa-bridge = {
    description = "Bridge trace-optimizer templates into GEPA-ready datasets";
    after = [ "hermes-evolution-foundry-trace-optimizer.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${foundryGepaBridge}/bin/hermes-evolution-foundry-gepa-bridge";
      ReadWritePaths = lib.mkForce [ "/var/lib/hermes/reports/evolution/gepa-bridge" ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/foundry"
        "/var/lib/hermes/reports/evolution/trace-optimizer"
      ];
      InaccessiblePaths = lib.mkForce [
        "-/var/lib/hermes/secrets"
        "-/var/lib/hermes/.hermes/.env"
      ];
    };
  };

  systemd.services.hermes-validate-foundry-gepa-bridge = {
    description = "Validate Foundry GEPA bridge output boundaries";
    after = [ "hermes-evolution-foundry-gepa-bridge.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${validateFoundryGepaBridge}/bin/hermes-validate-foundry-gepa-bridge";
      ReadWritePaths = lib.mkForce [ ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/reports/evolution/gepa-bridge"
      ];
    };
  };

  systemd.services.hermes-evolution-foundry-observatory-health = {
    description = "Run Foundry observatory health report on judge audit log";
    after = [ "hermes-evolution-foundry-gepa-bridge.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${foundryObservatoryHealth}/bin/hermes-evolution-foundry-observatory-health";
      ReadWritePaths = lib.mkForce [
        "/var/lib/hermes/reports/evolution/observatory"
      ];
    };
  };

  systemd.services.hermes-validate-foundry-observatory-health = {
    description = "Validate Foundry observatory health report boundaries";
    after = [ "hermes-evolution-foundry-observatory-health.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${validateFoundryObservatoryHealth}/bin/hermes-validate-foundry-observatory-health";
      ReadWritePaths = lib.mkForce [ ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/reports/evolution/observatory"
      ];
    };
  };

  systemd.services.hermes-evolution-foundry-content-evolution = {
    description = "Run Foundry skill content evolution manually";
    after = [ "hermes-evolution-foundry-observatory-health.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${foundryContentEvolution}/bin/hermes-evolution-foundry-content-evolution";
      Environment = [
        "HOME=/var/lib/hermes"
        "HERMES_HOME=/var/lib/hermes/.hermes"
      ];
      ReadWritePaths = lib.mkForce [ "/var/lib/hermes/reports/evolution/content-evolution" ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/foundry"
        "/var/lib/hermes/.hermes"
      ];
      InaccessiblePaths = lib.mkForce [
        "-/var/lib/hermes/secrets"
        "-/var/lib/hermes/.hermes/.env"
      ];
    };
  };

  systemd.services.hermes-validate-foundry-content-evolution = {
    description = "Validate Foundry content evolution output boundaries";
    after = [ "hermes-evolution-foundry-content-evolution.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${validateFoundryContentEvolution}/bin/hermes-validate-foundry-content-evolution";
      ReadWritePaths = lib.mkForce [ ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/reports/evolution/content-evolution"
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


  systemd.services.hermes-autonomous-evolution-chain = {
    description = "Run autonomous evolution chain on detected sessions";
    after = [ "hermes-agent.service" ];
    serviceConfig = commonServiceConfig // {
      ExecStart = "${autonomousEvolutionChain}/bin/hermes-autonomous-evolution-chain";
      Environment = [ "NIX_LD_LIBRARY_PATH=/run/current-system/sw/share/nix-ld/lib" ];
      ReadWritePaths = lib.mkForce [
        "/var/lib/hermes/reports/evolution"
        "/var/lib/hermes/.hermes/sessions"
      ];
      ReadOnlyPaths = lib.mkForce [
        "/var/lib/hermes/foundry"
        "/var/lib/hermes/foundry-venv"
      ];
      InaccessiblePaths = lib.mkForce [
        "-/var/lib/hermes/secrets"
        "-/var/lib/hermes/.hermes/.env"
      ];
    };
  };

  systemd.timers.hermes-autonomous-evolution-chain = {
    description = "Fire autonomous evolution chain every 30 minutes";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "1min";
      OnUnitActiveSec = "3min";
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
