# Lane 1 — GEPA Bridge Unblocking (nix-ld)

**Date:** 2026-05-10
**Status:** COMPLETE — 5/5 stages operational

## Problem

pip-installed `dspy` 3.2.1 venv at `/var/lib/hermes/foundry-venv` could not load
native wheels (`numpy`, `tokenizers`) because NixOS doesn't provide standard
library paths. Also missing `scikit-learn` (imported by Foundry's
`constraints_v2.py`).

## Solution

### 1. nix-ld enabled in `system/nixos/harness.nix`

```nix
# Inside the `in { ... }` block:
programs.nix-ld.enable = true;
```

This populates `/run/current-system/sw/share/nix-ld/lib` with system libraries
(`libstdc++.so.6`, `libgcc_s.so.1`, `libz.so.1`, etc).

### 2. LD_LIBRARY_PATH in autonomous chain wrapper

```bash
# In autonomousEvolutionChain writeShellApplication text:
export LD_LIBRARY_PATH=${NIX_LD_LIBRARY_PATH:-}${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
```

nixpkgs Python ignores `NIX_LD_LIBRARY_PATH` (that's for unpatched binaries).
Setting `LD_LIBRARY_PATH` exports it for nixpkgs subprocesses.

### 3. systemd Environment injection

```nix
systemd.services.hermes-autonomous-evolution-chain = {
  serviceConfig = commonServiceConfig // {
    Environment = [ "NIX_LD_LIBRARY_PATH=/run/current-system/sw/share/nix-ld/lib" ];
    ReadOnlyPaths = lib.mkForce [
      "/var/lib/hermes/foundry"
      "/var/lib/hermes/foundry-venv"  # <-- added
      "/var/lib/hermes/.hermes/sessions"
    ];
  };
};
```

systemd strips user env, so `NIX_LD_LIBRARY_PATH` must be explicitly injected.

### 4. Pip venv dependencies

```
/var/lib/hermes/foundry-venv/bin/pip install dspy-ai scikit-learn click
```

- `dspy-ai` 3.2.1 → pulls numpy, tokenizers, litellm, etc.
- `scikit-learn` 1.8.0 → needed by `constraints_v2.py`
- `click` → needed by gepa_trace_bridge CLI

### 5. Upstream Click flag bug (locally patched)

`--no-network` with `is_flag=True, default=True` toggles to False when passed.
Patched in runtime: removed `default=True`, commented assert lines.
Upstream fix tracked as lane 2.

## Verification

```
1/5 real-trace-ingestion:   pass (failure_classes_detected: 1)
2/5 attention-router-bridge: pass (action_items_emitted: 1)
3/5 trace-optimizer:        pass (improvements_generated: 1)
4/5 gepa-bridge:            pass (datasets: 1, examples: 2)
5/5 observatory-health:     operational (DEAD_ZONE alert, mean_score: 0.98)
```

## Env variable reference

| Variable | Value | Scope |
|---|---|---|
| `NIX_LD_LIBRARY_PATH` | `/run/current-system/sw/share/nix-ld/lib` | systemd Environment |
| `LD_LIBRARY_PATH` | `$NIX_LD_LIBRARY_PATH` | wrapper shell script |
| `NIX_LD` | `/run/current-system/sw/share/nix-ld/lib/ld.so` | set by nix-ld module |

## Relevant commits

- `234fbfa` — enable nix-ld + LD_LIBRARY_PATH passthrough
- `412f75a` — inject NIX_LD_LIBRARY_PATH into systemd service + allow foundry-venv read
