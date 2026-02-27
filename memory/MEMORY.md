# Project Memory: auto-code-proj

## What This Project Does
A Python harness that drives the Claude Code SDK to autonomously build web applications.
Two-agent pattern: initializer (generates feature_list.json) + coding agent (implements features).

## Architecture (6 core files + 2 new)
- `autonomous_agent_demo.py` — CLI entry point, argparse, orchestrates configure + agent loop
- `agent.py` — Main agent loop logic (run_autonomous_agent, run_agent_session)
- `client.py` — Creates ClaudeSDKClient with security settings and hooks
- `security.py` — Pre-tool-use bash command allowlist hook (bash_security_hook)
- `progress.py` — Tracks feature_list.json passing/total count
- `prompts.py` — Loads .md prompt files from prompts/ directory
- `config.py` — NEW: Central config from .env via python-dotenv (get_config singleton)
- `configure.py` — NEW: AI agent that reads prompts/ and writes .env (run_configure)

## Config System (.env-driven)
- All config loaded from `.env` via `config.py` → `ProjectConfig` dataclass
- `get_config()` is an `@lru_cache(maxsize=1)` singleton
- `reload_config()` clears cache and re-reads .env (used after --configure writes it)
- Computed properties: `allowed_commands`, `allowed_processes`, `dev_server_url`
- Framework→command mappings in `FRAMEWORK_COMMANDS` and `PACKAGE_MANAGER_COMMANDS`
- Use `+` to combine: `PACKAGE_MANAGER=composer+npm`

## Key Config Fields & Defaults
| Key | Default |
|-----|---------|
| CLAUDE_MODEL | claude-sonnet-4-6 |
| CONFIGURE_MODEL | claude-haiku-4-5-20251001 |
| FRAMEWORK | generic |
| PACKAGE_MANAGER | npm |
| DEV_SERVER_CMD | npm run dev |
| DEV_SERVER_PORT | 3000 |
| FEATURE_LIST_FILE | feature_list.json |
| PROJECT_DIR_PREFIX | generations/ |

## Workflow
```
# First time:
python autonomous_agent_demo.py --project-dir ./my_project --configure
# Subsequent:
python autonomous_agent_demo.py --project-dir ./my_project
```

## Security
- `security.py` derives allowlist from `get_config().allowed_commands` (no hardcoded list)
- pkill targets derived from `get_config().allowed_processes`
- Init script validated against `get_config().init_script_name`
- Configure agent is read-only (only Read + Glob tools, no Bash)

## Tech Stack
- Python 3.12+, claude-code-sdk>=0.0.25, python-dotenv>=1.0.0
- No git repo (as of last session)
- prompts/ directory: app-spec.txt, initializer_prompt.md, coding_prompt.md
