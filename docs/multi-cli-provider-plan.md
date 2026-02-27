# Multi-CLI Provider Integration Plan

## Summary

Implement provider support for `claude`, `codex`, `omp`, and `opencode` with:

- first-run interactive provider selection
- persistent provider ID in `.env`
- per-run override + optional save
- capability-aware native flags or prompt shims
- explicit degraded-capability warnings

## Scope

- `config.py`: provider types, capability matrix inputs, runtime config, validation.
- `acaps.py`: CLI flags and provider resolution flow.
- `prompter.py`, `configure.py`, `agent.py`: route all CLI calls through provider adapter.
- `.env.template`, `README.md`: provider config keys and parity caveats.
- tests: provider resolution, validation, and persistence behavior.

## API / Config Additions

- `--agent-cli {claude,codex,omp,opencode}`
- `--save-agent-cli`
- `.env`:
  - `AGENT_CLI_ID`
  - `AGENT_CLI_BIN_CLAUDE`, `AGENT_CLI_BIN_CODEX`, `AGENT_CLI_BIN_OMP`, `AGENT_CLI_BIN_OPENCODE`
  - `AGENT_CLI_MODEL_CLAUDE`, `AGENT_CLI_MODEL_CODEX`, `AGENT_CLI_MODEL_OMP`, `AGENT_CLI_MODEL_OPENCODE`
  - `AGENT_CLI_WARN_ON_DEGRADED_CAPS`
  - `AGENT_CLI_REQUIRE_JSON_OUTPUT`

## Capability Policy

- Use native provider flags where available.
- If native parity is missing, apply prompt shims:
  - system contract
  - tool policy contract
  - output contract (when needed)
- Warn users when running degraded-capability mode.

## Expected Tradeoffs

- Consistency target is behavioral parity, not identical outputs.
- Model/harness differences can produce regressions or enhancements.
- Some providers may lack native sandbox/approval controls; ACAP uses best-effort guardrails and explicit warnings.
