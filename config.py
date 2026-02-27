"""
Central Configuration Module
==============================

Loads all project configuration from .env via python-dotenv.
Provides a ProjectConfig dataclass and get_config() singleton.

Usage:
    from config import get_config
    cfg = get_config()
    print(cfg.claude_model)
    print(cfg.allowed_commands)
"""

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

# Load .env file if it exists
load_dotenv(dotenv_path=Path(__file__).parent / ".env")


# --- Framework / Package Manager → Command Mappings ---

FRAMEWORK_COMMANDS: dict[str, set[str]] = {
    "laravel": {"php", "composer"},
    "django": {"python", "pip"},
    "fastapi": {"python", "pip", "uvicorn"},
    "rails": {"ruby", "bundle", "rails"},
    "flask": {"python", "pip"},
    # nextjs/react/vue/express covered by JS package manager
}

PACKAGE_MANAGER_COMMANDS: dict[str, set[str]] = {
    "npm": {"npm", "node", "npx"},
    "bun": {"bun", "bunx"},
    "yarn": {"yarn", "node"},
    "pnpm": {"pnpm", "node"},
    "pip": {"pip", "python"},
    "composer": {"composer", "php"},
    "cargo": {"cargo", "rustc"},
    "go": {"go"},
}

BASE_COMMANDS: set[str] = {
    "ls",
    "cat",
    "head",
    "tail",
    "wc",
    "grep",
    "cp",
    "mkdir",
    "chmod",
    "pwd",
    "ps",
    "lsof",
    "sleep",
    "pkill",
    "git",
}

# Allowed process names for pkill — derived from package manager + framework
FRAMEWORK_PROCESSES: dict[str, set[str]] = {
    "laravel": {"php"},
    "django": {"python"},
    "fastapi": {"python", "uvicorn"},
    "rails": {"ruby"},
    "flask": {"python"},
}

PACKAGE_MANAGER_PROCESSES: dict[str, set[str]] = {
    "npm": {"node", "npm", "npx", "vite", "next"},
    "bun": {"bun", "bunx"},
    "yarn": {"yarn", "node"},
    "pnpm": {"pnpm", "node"},
    "pip": {"python"},
    "composer": {"php"},
    "cargo": {"cargo"},
    "go": {},
}

# Default system prompt
DEFAULT_SYSTEM_PROMPT = (
    "You are an expert full-stack developer building a production-quality web application. "
    "Default to a Turborepo monorepo using Bun as the primary package manager "
    "with pnpm as a fallback unless the user specifies otherwise."
)

ProviderId = Literal["claude", "codex", "omp", "opencode"]
VALID_PROVIDER_IDS: set[str] = {"claude", "codex", "omp", "opencode"}


def normalize_provider_id(value: str | None) -> str:
    """
    Normalize provider IDs with backwards-compatible fallback.

    Any missing/invalid value defaults to "claude".
    """
    if not value:
        return "claude"
    normalized = value.strip().lower()
    if normalized in VALID_PROVIDER_IDS:
        return normalized
    return "claude"


def _parse_bool_env(value: str | None, default: bool) -> bool:
    """Parse boolean-like env values with sensible defaults."""
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


@dataclass
class ProjectConfig:
    """All project configuration, loaded from .env with sensible defaults."""

    # AI Settings
    claude_model: str = "claude-sonnet-4-6"
    configure_model: str = "claude-haiku-4-5-20251001"
    agent_system_prompt: str = DEFAULT_SYSTEM_PROMPT
    max_turns: int = 1000
    auto_continue_delay: float = 3.0

    # Tech Stack
    framework: str = "generic"
    package_manager: str = "bun+pnpm"
    dev_server_cmd: str = "bun run dev"
    dev_server_port: int = 3000

    # Security Extensions (comma-separated strings, parsed to sets at runtime)
    extra_allowed_commands: str = ""
    extra_allowed_processes: str = ""

    # File Names
    feature_list_file: str = "feature_list.json"
    init_script_name: str = "init.sh"
    app_spec_filename: str = "app-spec.txt"
    settings_filename: str = ".claude_settings.json"

    # Directory / Prompt Files
    project_dir_prefix: str = "generations/"
    prompts_dir: str = "prompts"
    initializer_prompt_name: str = "initializer_prompt"
    coding_prompt_name: str = "coding_prompt"

    # Agent CLI Provider Selection / Runtime
    agent_cli_id: ProviderId = "claude"
    agent_cli_bin_claude: str = "claude"
    agent_cli_bin_codex: str = "codex"
    agent_cli_bin_omp: str = "omp"
    agent_cli_bin_opencode: str = "opencode"
    agent_cli_model_claude: str = "claude-sonnet-4-6"
    agent_cli_model_codex: str = "gpt-5-codex"
    agent_cli_model_omp: str = "claude-sonnet-4-5"
    agent_cli_model_opencode: str = "claude-sonnet-4-5"
    agent_cli_warn_on_degraded_caps: bool = True
    agent_cli_require_json_output: bool = True
    agent_cli_non_interactive: bool = True
    agent_cli_auto_approve_fallback: bool = True
    agent_cli_dangerous_fallback: bool = True
    prompt_autonomy_override: bool = True

    @property
    def allowed_commands(self) -> set[str]:
        """
        Compute the full allowlist of bash commands.

        BASE_COMMANDS
        + framework-specific commands (from FRAMEWORK_COMMANDS)
        + package manager commands (from PACKAGE_MANAGER_COMMANDS)
        + init_script_name
        + extra_allowed_commands (comma-separated from .env)
        """
        commands: set[str] = set(BASE_COMMANDS)

        # Add framework commands
        for fw in self.framework.split("+"):
            fw = fw.strip().lower()
            commands.update(FRAMEWORK_COMMANDS.get(fw, set()))

        # Add package manager commands
        for pm in self.package_manager.split("+"):
            pm = pm.strip().lower()
            commands.update(PACKAGE_MANAGER_COMMANDS.get(pm, set()))

        # Add init script name
        commands.add(self.init_script_name)

        # Add extras from .env
        if self.extra_allowed_commands:
            for cmd in self.extra_allowed_commands.split(","):
                cmd = cmd.strip()
                if cmd:
                    commands.add(cmd)

        return commands

    @property
    def allowed_processes(self) -> set[str]:
        """
        Compute allowed process names for pkill validation.

        Derived from framework + package manager process mappings
        + extra_allowed_processes (comma-separated from .env)
        """
        processes: set[str] = set()

        # Add framework processes
        for fw in self.framework.split("+"):
            fw = fw.strip().lower()
            processes.update(FRAMEWORK_PROCESSES.get(fw, set()))

        # Add package manager processes
        for pm in self.package_manager.split("+"):
            pm = pm.strip().lower()
            processes.update(PACKAGE_MANAGER_PROCESSES.get(pm, set()))

        # Add extras from .env
        if self.extra_allowed_processes:
            for proc in self.extra_allowed_processes.split(","):
                proc = proc.strip()
                if proc:
                    processes.add(proc)

        return processes

    @property
    def dev_server_url(self) -> str:
        """Construct the dev server URL from the port."""
        return f"http://localhost:{self.dev_server_port}"


@lru_cache(maxsize=1)
def get_config() -> ProjectConfig:
    """
    Return the singleton ProjectConfig loaded from environment variables.

    Call invalidate_config_cache() to reload after writing a new .env.
    """
    return ProjectConfig(
        claude_model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
        configure_model=os.environ.get(
            "CONFIGURE_MODEL", "claude-haiku-4-5-20251001"
        ),
        agent_system_prompt=os.environ.get(
            "AGENT_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT
        ),
        max_turns=int(os.environ.get("MAX_TURNS", "1000")),
        auto_continue_delay=float(
            os.environ.get("AUTO_CONTINUE_DELAY_SECONDS", "3")
        ),
        framework=os.environ.get("FRAMEWORK", "generic"),
        package_manager=os.environ.get("PACKAGE_MANAGER", "bun+pnpm"),
        dev_server_cmd=os.environ.get("DEV_SERVER_CMD", "bun run dev"),
        dev_server_port=int(os.environ.get("DEV_SERVER_PORT", "3000")),
        extra_allowed_commands=os.environ.get("EXTRA_ALLOWED_COMMANDS", ""),
        extra_allowed_processes=os.environ.get("EXTRA_ALLOWED_PROCESSES", ""),
        feature_list_file=os.environ.get("FEATURE_LIST_FILE", "feature_list.json"),
        init_script_name=os.environ.get("INIT_SCRIPT_NAME", "init.sh"),
        app_spec_filename=os.environ.get("APP_SPEC_FILENAME", "app-spec.txt"),
        settings_filename=os.environ.get("SETTINGS_FILENAME", ".claude_settings.json"),
        project_dir_prefix=os.environ.get("PROJECT_DIR_PREFIX", "generations/"),
        prompts_dir=os.environ.get("PROMPTS_DIR", "prompts"),
        initializer_prompt_name=os.environ.get(
            "INITIALIZER_PROMPT_NAME", "initializer_prompt"
        ),
        coding_prompt_name=os.environ.get("CODING_PROMPT_NAME", "coding_prompt"),
        agent_cli_id=normalize_provider_id(os.environ.get("AGENT_CLI_ID", "claude")),  # type: ignore[arg-type]
        agent_cli_bin_claude=os.environ.get("AGENT_CLI_BIN_CLAUDE", "claude"),
        agent_cli_bin_codex=os.environ.get("AGENT_CLI_BIN_CODEX", "codex"),
        agent_cli_bin_omp=os.environ.get("AGENT_CLI_BIN_OMP", "omp"),
        agent_cli_bin_opencode=os.environ.get("AGENT_CLI_BIN_OPENCODE", "opencode"),
        agent_cli_model_claude=os.environ.get(
            "AGENT_CLI_MODEL_CLAUDE", "claude-sonnet-4-6"
        ),
        agent_cli_model_codex=os.environ.get(
            "AGENT_CLI_MODEL_CODEX", "gpt-5-codex"
        ),
        agent_cli_model_omp=os.environ.get(
            "AGENT_CLI_MODEL_OMP", "claude-sonnet-4-5"
        ),
        agent_cli_model_opencode=os.environ.get(
            "AGENT_CLI_MODEL_OPENCODE", "claude-sonnet-4-5"
        ),
        agent_cli_warn_on_degraded_caps=_parse_bool_env(
            os.environ.get("AGENT_CLI_WARN_ON_DEGRADED_CAPS"), True
        ),
        agent_cli_require_json_output=_parse_bool_env(
            os.environ.get("AGENT_CLI_REQUIRE_JSON_OUTPUT"), True
        ),
        agent_cli_non_interactive=_parse_bool_env(
            os.environ.get("AGENT_CLI_NON_INTERACTIVE"), True
        ),
        agent_cli_auto_approve_fallback=_parse_bool_env(
            os.environ.get("AGENT_CLI_AUTO_APPROVE_FALLBACK"), True
        ),
        agent_cli_dangerous_fallback=_parse_bool_env(
            os.environ.get("AGENT_CLI_DANGEROUS_FALLBACK"), True
        ),
        prompt_autonomy_override=_parse_bool_env(
            os.environ.get("PROMPT_AUTONOMY_OVERRIDE"), True
        ),
    )


def reload_config() -> ProjectConfig:
    """
    Reload configuration from disk (re-reads .env, clears cache).

    Call this after writing a new .env file.
    """
    get_config.cache_clear()
    load_dotenv(
        dotenv_path=Path(__file__).parent / ".env",
        override=True,
    )
    return get_config()
