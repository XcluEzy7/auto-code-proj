"""
Configuration Generator
========================

Uses the Claude Code SDK to read prompts/ files and generate a .env
configuration file tailored to the detected tech stack.

Usage (from acaps.py):
    from configure import run_configure
    await run_configure(configure_model="claude-haiku-4-5-20251001")

Or standalone:
    python configure.py
"""

import asyncio
import json
import os
from pathlib import Path

from config import get_config
from provider_cli import provider_default_model, run_prompt_task

# Hardcoded defaults for paths — .env doesn't exist yet when this runs
DEFAULT_PROMPTS_DIR = "prompts"
DEFAULT_APP_SPEC_FILENAME = "app-spec.txt"
DEFAULT_INITIALIZER_PROMPT = "initializer_prompt"
DEFAULT_CODING_PROMPT = "coding_prompt"

CONFIGURE_SYSTEM_PROMPT = """\
You are a project analyzer that reads application specification files and detects \
the tech stack to generate environment configuration.

When asked to analyze a project, you will:
1. Read the prompts/ directory files using Read and Glob tools
2. Identify the framework, package manager, dev server command, and port
3. Output ONLY a valid JSON object (no markdown, no explanation) with these exact keys:
   - framework: string (e.g. "laravel", "django", "rails", "flask", "fastapi", "generic")
     Use "+" to combine when multiple apply (e.g. "laravel+npm" is NOT valid here — \
framework is the backend framework only)
   - package_manager: string (e.g. "npm", "bun", "yarn", "pnpm", "pip", "composer", "cargo", "go")
     Use "+" to combine when multiple apply (e.g. "composer+pnpm")
   - dev_server_cmd: string (e.g. "bun run dev", "php artisan serve", "python manage.py runserver")
   - dev_server_port: integer (e.g. 3000, 8000, 8080)
   - agent_system_prompt: string (a tailored system prompt for an AI developer working on this stack)
   - claude_model: string (always "claude-sonnet-4-6")
   - configure_model: string (always "claude-haiku-4-5-20251001")
   - max_turns: integer (always 1000)
   - auto_continue_delay_seconds: integer (always 3)
   - feature_list_file: string (always "feature_list.json")
   - init_script_name: string (always "init.sh")
   - app_spec_filename: string (always "app-spec.txt")
   - settings_filename: string (always ".claude_settings.json")
   - project_dir_prefix: string (always "generations/")
   - prompts_dir: string (always "prompts")
   - initializer_prompt_name: string (always "initializer_prompt")
   - coding_prompt_name: string (always "coding_prompt")
   - extra_allowed_commands: string (comma-separated, empty if none needed)
   - extra_allowed_processes: string (comma-separated, empty if none needed)

The agent_system_prompt should be specific to the detected stack. For example:
- Laravel: "You are an expert Laravel/PHP developer building a production web application..."
- Django: "You are an expert Django/Python developer building a production web application..."
- React/Vite: "You are an expert React developer building a production web application..."

Output ONLY the JSON object, starting with { and ending with }. No other text.
"""


def build_configure_prompt(prompts_dir: str) -> str:
    """Build the prompt instructing the agent to analyze the project."""
    return f"""\
Please analyze the project specification files in the `{prompts_dir}/` directory.

Read the following files (use Glob to discover what's available, then Read to get contents):
- {prompts_dir}/app-spec.txt (or app_spec.txt)
- {prompts_dir}/initializer_prompt.md
- {prompts_dir}/coding_prompt.md

Based on what you find, detect the tech stack and output ONLY a JSON configuration object \
as described in your instructions. Start your response with {{ and end with }}.
"""


def _validate_json_object(
    obj: object,
    required_keys: set[str] | None,
    exact_keys: bool,
) -> tuple[bool, str]:
    """Validate the parsed JSON object shape."""
    if not isinstance(obj, dict):
        return False, f"Parsed JSON was {type(obj).__name__}, expected object"

    if not required_keys:
        return True, ""

    parsed_keys = set(obj.keys())
    missing = required_keys - parsed_keys
    if missing:
        return False, f"Missing required keys: {sorted(missing)}"

    if exact_keys and parsed_keys != required_keys:
        extra = parsed_keys - required_keys
        return False, f"Unexpected keys present: {sorted(extra)}"

    return True, ""


def extract_json_from_text(
    text: str,
    required_keys: set[str] | None = None,
    exact_keys: bool = False,
) -> dict:
    """
    Extract a JSON object from the agent's text output.

    The agent is instructed to output only JSON, but may occasionally
    include surrounding text. This handles that gracefully.
    """
    cleaned = text.strip()
    errors: list[str] = []

    # Stage 1: try parsing whole output directly
    try:
        parsed = json.loads(cleaned)
        valid, reason = _validate_json_object(parsed, required_keys, exact_keys)
        if valid:
            return parsed
        errors.append(f"Direct parse shape invalid: {reason}")
    except json.JSONDecodeError as exc:
        errors.append(f"Direct parse failed: {exc.msg} at pos {exc.pos}")

    # Stage 2: parse fenced code blocks (```json ... ``` or generic ``` ... ```)
    fenced_blocks: list[str] = []
    if "```" in cleaned:
        for marker in ("```json", "```JSON", "```"):
            start = 0
            while True:
                open_idx = cleaned.find(marker, start)
                if open_idx == -1:
                    break
                content_start = open_idx + len(marker)
                # Skip optional leading newline after fence marker
                if content_start < len(cleaned) and cleaned[content_start] == "\n":
                    content_start += 1
                close_idx = cleaned.find("```", content_start)
                if close_idx == -1:
                    break
                block = cleaned[content_start:close_idx].strip()
                if block:
                    fenced_blocks.append(block)
                start = close_idx + 3

    for i, block in enumerate(fenced_blocks, 1):
        try:
            parsed = json.loads(block)
            valid, reason = _validate_json_object(parsed, required_keys, exact_keys)
            if valid:
                return parsed
            errors.append(f"Fenced block #{i} shape invalid: {reason}")
        except json.JSONDecodeError as exc:
            errors.append(f"Fenced block #{i} parse failed: {exc.msg} at pos {exc.pos}")

    # Stage 3: scan for JSON objects with raw_decode from each '{' position
    decoder = json.JSONDecoder()
    for idx, char in enumerate(cleaned):
        if char != "{":
            continue
        candidate = cleaned[idx:]
        try:
            parsed, _ = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            continue

        valid, reason = _validate_json_object(parsed, required_keys, exact_keys)
        if valid:
            return parsed
        errors.append(f"raw_decode object at index {idx} shape invalid: {reason}")

    start_preview = cleaned[:300]
    end_preview = cleaned[-300:] if len(cleaned) > 300 else cleaned
    raise ValueError(
        "Could not extract valid JSON from agent output.\n"
        f"Required keys: {sorted(required_keys) if required_keys else 'none'}\n"
        f"Exact keys required: {exact_keys}\n"
        f"Parsing stages attempted: {' | '.join(errors[:8])}\n"
        f"Output start:\n{start_preview}\n\n"
        f"Output end:\n{end_preview}"
    )


def write_env_file(config_data: dict, env_path: Path | None = None) -> Path:
    """
    Write a documented .env file from the detected configuration.

    Args:
        config_data: Dict of config key→value from the configure agent
        env_path: Path to write to (default: .env in project root)

    Returns:
        Path to the written .env file
    """
    if env_path is None:
        env_path = Path(__file__).parent / ".env"

    lines = [
        "# Auto-generated by configure.py",
        "# Run: python acaps.py --configure  to regenerate",
        "",
        "# =============================================================================",
        "# AI Settings",
        "# =============================================================================",
        "",
        f"CLAUDE_MODEL={config_data.get('claude_model', 'claude-sonnet-4-6')}",
        f"CONFIGURE_MODEL={config_data.get('configure_model', 'claude-haiku-4-5-20251001')}",
        f"MAX_TURNS={config_data.get('max_turns', 1000)}",
        f"AUTO_CONTINUE_DELAY_SECONDS={config_data.get('auto_continue_delay_seconds', 3)}",
        "",
        "# Agent system prompt (single line)",
        f"AGENT_SYSTEM_PROMPT={config_data.get('agent_system_prompt', 'You are an expert full-stack developer building a production-quality web application.')}",
        "",
        "# =============================================================================",
        "# Tech Stack",
        "# =============================================================================",
        "",
        "# Framework: laravel, django, fastapi, rails, flask, generic",
        f"FRAMEWORK={config_data.get('framework', 'generic')}",
        "",
        "# Package manager: npm, bun, yarn, pnpm, pip, composer, cargo, go",
        "# Use + to combine: composer+pnpm",
        f"PACKAGE_MANAGER={config_data.get('package_manager', 'bun+pnpm')}",
        "",
        "# Command to start the dev server",
        f"DEV_SERVER_CMD={config_data.get('dev_server_cmd', 'bun run dev')}",
        "",
        "# Port the dev server listens on",
        f"DEV_SERVER_PORT={config_data.get('dev_server_port', 3000)}",
        "",
        "# =============================================================================",
        "# Security Extensions",
        "# =============================================================================",
        "",
        "# Additional bash commands to allow (comma-separated, e.g. 'make,cmake')",
        f"EXTRA_ALLOWED_COMMANDS={config_data.get('extra_allowed_commands', '')}",
        "",
        "# Additional process names for pkill allowlist (comma-separated)",
        f"EXTRA_ALLOWED_PROCESSES={config_data.get('extra_allowed_processes', '')}",
        "",
        "# =============================================================================",
        "# File Names",
        "# =============================================================================",
        "",
        f"FEATURE_LIST_FILE={config_data.get('feature_list_file', 'feature_list.json')}",
        f"INIT_SCRIPT_NAME={config_data.get('init_script_name', 'init.sh')}",
        f"APP_SPEC_FILENAME={config_data.get('app_spec_filename', 'app-spec.txt')}",
        f"SETTINGS_FILENAME={config_data.get('settings_filename', '.claude_settings.json')}",
        "",
        "# =============================================================================",
        "# Prompt Files",
        "# =============================================================================",
        "",
        f"PROJECT_DIR_PREFIX={config_data.get('project_dir_prefix', 'generations/')}",
        f"PROMPTS_DIR={config_data.get('prompts_dir', 'prompts')}",
        f"INITIALIZER_PROMPT_NAME={config_data.get('initializer_prompt_name', 'initializer_prompt')}",
        f"CODING_PROMPT_NAME={config_data.get('coding_prompt_name', 'coding_prompt')}",
        "",
        "# =============================================================================",
        "# Agent CLI Provider",
        "# =============================================================================",
        "",
        f"AGENT_CLI_ID={os.environ.get('AGENT_CLI_ID', 'claude')}",
        f"AGENT_CLI_BIN_CLAUDE={os.environ.get('AGENT_CLI_BIN_CLAUDE', 'claude')}",
        f"AGENT_CLI_BIN_CODEX={os.environ.get('AGENT_CLI_BIN_CODEX', 'codex')}",
        f"AGENT_CLI_BIN_OMP={os.environ.get('AGENT_CLI_BIN_OMP', 'omp')}",
        f"AGENT_CLI_BIN_OPENCODE={os.environ.get('AGENT_CLI_BIN_OPENCODE', 'opencode')}",
        f"AGENT_CLI_MODEL_CLAUDE={os.environ.get('AGENT_CLI_MODEL_CLAUDE', 'claude-sonnet-4-6')}",
        f"AGENT_CLI_MODEL_CODEX={os.environ.get('AGENT_CLI_MODEL_CODEX', 'gpt-5-codex')}",
        f"AGENT_CLI_MODEL_OMP={os.environ.get('AGENT_CLI_MODEL_OMP', 'claude-sonnet-4-5')}",
        f"AGENT_CLI_MODEL_OPENCODE={os.environ.get('AGENT_CLI_MODEL_OPENCODE', 'claude-sonnet-4-5')}",
        f"AGENT_CLI_WARN_ON_DEGRADED_CAPS={os.environ.get('AGENT_CLI_WARN_ON_DEGRADED_CAPS', 'true')}",
        f"AGENT_CLI_REQUIRE_JSON_OUTPUT={os.environ.get('AGENT_CLI_REQUIRE_JSON_OUTPUT', 'true')}",
        "",
    ]

    env_path.write_text("\n".join(lines))
    return env_path


async def run_configure(
    configure_model: str | None = None,
    prompts_dir: str = DEFAULT_PROMPTS_DIR,
    provider_id: str | None = None,
) -> dict:
    """
    Run the configuration detection agent.

    Reads prompts/ files via claude -p headless CLI,
    extracts detected config as JSON, writes .env, and returns the config dict.

    Args:
        configure_model: Model to use for configuration detection.
                         Falls back to CONFIGURE_MODEL env var, then haiku default.
        prompts_dir: Path to the prompts directory (relative to cwd).

    Returns:
        Dict of detected configuration values.
    """
    cfg = get_config()
    provider = provider_id or cfg.agent_cli_id
    model = (
        configure_model
        or os.environ.get("CONFIGURE_MODEL")
        or provider_default_model(provider, cfg)
    )

    print(f"\n[Configure] Detecting tech stack with {model} via {provider}...\n")

    result = run_prompt_task(
        provider_id=provider,
        model=model,
        system_prompt=CONFIGURE_SYSTEM_PROMPT,
        prompt=build_configure_prompt(prompts_dir),
        cwd=Path.cwd(),
        cfg=cfg,
        allowed_tools="Read,Glob,Edit,Bash,Task",
    )

    if result.returncode != 0:
        error_msg = result.stderr[:500] if result.stderr else "(no stderr)"
        raise RuntimeError(f"Configure agent failed: {error_msg}")

    config_data = extract_json_from_text(result.stdout)
    env_path = write_env_file(config_data)
    print(f"\n✓ Configuration written to: {env_path}")
    return config_data


if __name__ == "__main__":
    asyncio.run(run_configure())
