"""
Provider CLI Adapter
====================

Normalizes invocation across supported agent CLIs and applies prompt-based
workarounds when providers lack native capability parity.
"""

import shutil
import subprocess
import sys
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import ProjectConfig, VALID_PROVIDER_IDS, normalize_provider_id


@dataclass(frozen=True)
class ProviderCapabilities:
    """Capability flags used to choose native flags vs shim behavior."""

    supports_native_system_prompt: bool
    supports_native_append_system_prompt: bool
    supports_native_tool_allowlist: bool
    supports_native_sandbox_policy: bool
    supports_native_approval_policy: bool
    supports_json_stream: bool
    supports_session_resume: bool


CAPABILITIES: dict[str, ProviderCapabilities] = {
    "claude": ProviderCapabilities(
        supports_native_system_prompt=True,
        supports_native_append_system_prompt=True,
        supports_native_tool_allowlist=True,
        supports_native_sandbox_policy=True,
        supports_native_approval_policy=True,
        supports_json_stream=False,
        supports_session_resume=False,
    ),
    "codex": ProviderCapabilities(
        supports_native_system_prompt=False,
        supports_native_append_system_prompt=False,
        supports_native_tool_allowlist=False,
        supports_native_sandbox_policy=True,
        supports_native_approval_policy=True,
        supports_json_stream=True,
        supports_session_resume=True,
    ),
    "omp": ProviderCapabilities(
        supports_native_system_prompt=True,
        supports_native_append_system_prompt=True,
        supports_native_tool_allowlist=True,
        supports_native_sandbox_policy=False,
        supports_native_approval_policy=False,
        supports_json_stream=True,
        supports_session_resume=False,
    ),
    "opencode": ProviderCapabilities(
        supports_native_system_prompt=False,
        supports_native_append_system_prompt=False,
        supports_native_tool_allowlist=False,
        supports_native_sandbox_policy=False,
        supports_native_approval_policy=False,
        supports_json_stream=True,
        supports_session_resume=True,
    ),
}

INSTALL_HINTS: dict[str, str] = {
    "claude": "Install/auth via Claude Code, then run: claude login",
    "codex": "Install/setup Codex CLI: https://developers.openai.com/codex/cli/reference",
    "omp": "Install/setup Oh-My-Pi CLI: https://github.com/can1357/oh-my-pi?tab=readme-ov-file#cli-reference",
    "opencode": "Install/setup Opencode CLI: https://opencode.ai/docs/cli/",
}


def provider_binary(provider_id: str, cfg: ProjectConfig) -> str:
    """Resolve the executable name/path for the selected provider."""
    if provider_id == "claude":
        return cfg.agent_cli_bin_claude
    if provider_id == "codex":
        return cfg.agent_cli_bin_codex
    if provider_id == "omp":
        return cfg.agent_cli_bin_omp
    return cfg.agent_cli_bin_opencode


def provider_default_model(provider_id: str, cfg: ProjectConfig) -> str:
    """Resolve per-provider default model from config."""
    if provider_id == "claude":
        return cfg.agent_cli_model_claude or cfg.claude_model
    if provider_id == "codex":
        return cfg.agent_cli_model_codex
    if provider_id == "omp":
        return cfg.agent_cli_model_omp
    return cfg.agent_cli_model_opencode


def ensure_provider_binary_exists(provider_id: str, cfg: ProjectConfig) -> str:
    """Fail fast with provider-specific install hints if executable is missing."""
    binary = provider_binary(provider_id, cfg)
    if shutil.which(binary):
        return binary
    raise RuntimeError(
        f"Selected provider '{provider_id}' is not installed or not in PATH "
        f"(binary: {binary}). {INSTALL_HINTS[provider_id]}"
    )


def print_degraded_capability_warning(provider_id: str, cfg: ProjectConfig) -> None:
    """Print explicit warnings for best-effort providers without native parity."""
    if not cfg.agent_cli_warn_on_degraded_caps:
        return
    if provider_id == "claude":
        return
    caps = CAPABILITIES[provider_id]
    gaps: list[str] = []
    if not caps.supports_native_system_prompt:
        gaps.append("system prompt is shimmed into user prompt")
    if not caps.supports_native_tool_allowlist:
        gaps.append("tool policy is prompt-based (best effort)")
    if not caps.supports_native_sandbox_policy:
        gaps.append("no native sandbox policy flag")
    if not caps.supports_native_approval_policy:
        gaps.append("no native approval policy flag")
    if gaps:
        print(
            "[Warning] Reduced capability parity for provider "
            f"'{provider_id}': {', '.join(gaps)}."
        )


def _shim_prompt(
    prompt: str,
    system_prompt: str,
    allowed_tools: Optional[str] = None,
    require_json_output: bool = False,
) -> str:
    """
    Inject policy/system contracts into user prompt when native flags are missing.
    """
    blocks = [
        "=== SYSTEM CONTRACT ===",
        system_prompt.strip(),
    ]
    if allowed_tools:
        blocks.extend(
            [
                "",
                "=== TOOL POLICY CONTRACT ===",
                (
                    "Prefer only these tool categories when available: "
                    f"{allowed_tools}. If unsupported by this harness, emulate "
                    "equivalent behavior conservatively."
                ),
            ]
        )
    if require_json_output:
        blocks.extend(
            [
                "",
                "=== OUTPUT CONTRACT ===",
                "Return only valid JSON with no markdown fences or explanations.",
            ]
        )
    blocks.extend(["", "=== TASK ===", prompt])
    return "\n".join(blocks)


def upsert_env_var(key: str, value: str, env_path: Path) -> None:
    """Insert/update KEY=value in an env file without touching unrelated lines."""
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    updated = False
    prefix = f"{key}="
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = f"{key}={value}"
            updated = True
            break

    if not updated:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def has_env_var(key: str, env_path: Path) -> bool:
    """Check whether an env key exists in the env file."""
    if not env_path.exists():
        return False
    prefix = f"{key}="
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(prefix):
            return True
    return False


def _interactive_provider_choice() -> str:
    """Prompt user once for provider selection."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise RuntimeError(
            "No AGENT_CLI_ID configured and no interactive terminal available. "
            "Provide --agent-cli {claude,codex,omp,opencode}."
        )

    options = ["claude", "codex", "omp", "opencode"]
    print("\nSelect agent CLI provider:")
    for idx, value in enumerate(options, start=1):
        print(f"  {idx}. {value}")

    while True:
        choice = input("Enter number [1-4]: ").strip()
        if choice in {"1", "2", "3", "4"}:
            return options[int(choice) - 1]
        print("Invalid selection. Choose 1, 2, 3, or 4.")


def resolve_provider_for_run(
    cfg: ProjectConfig,
    cli_override: Optional[str],
    save_override: bool,
    env_path: Path,
) -> str:
    """
    Resolve provider for this run, with first-run interactive persistence and
    optional override persistence.
    """
    if cli_override:
        provider_id = normalize_provider_id(cli_override)
        if cli_override.lower() not in VALID_PROVIDER_IDS:
            print(
                f"[Warning] Unsupported --agent-cli '{cli_override}', defaulting to "
                "'claude'."
            )
        if save_override:
            upsert_env_var("AGENT_CLI_ID", provider_id, env_path)
        os.environ["AGENT_CLI_ID"] = provider_id
        return provider_id

    existing = (cfg.agent_cli_id or "").strip().lower()
    if has_env_var("AGENT_CLI_ID", env_path) and existing in VALID_PROVIDER_IDS:
        return existing

    provider_id = _interactive_provider_choice()
    upsert_env_var("AGENT_CLI_ID", provider_id, env_path)
    os.environ["AGENT_CLI_ID"] = provider_id
    return provider_id


def run_prompt_task(
    provider_id: str,
    model: str,
    system_prompt: str,
    prompt: str,
    cwd: Path,
    cfg: ProjectConfig,
    allowed_tools: str = "Edit,Bash,Task",
) -> subprocess.CompletedProcess[str]:
    """
    Run a one-shot prompt task across providers (analysis/config/generation).
    """
    provider_id = normalize_provider_id(provider_id)
    binary = ensure_provider_binary_exists(provider_id, cfg)
    caps = CAPABILITIES[provider_id]
    require_json = cfg.agent_cli_require_json_output

    if provider_id == "claude":
        return subprocess.run(
            [
                binary,
                "-p",
                "--model",
                model,
                "--allowedTools",
                allowed_tools,
                "--system-prompt",
                system_prompt,
            ],
            input=prompt,
            capture_output=True,
            text=True,
            cwd=str(cwd),
        )

    query = prompt
    needs_output_contract_shim = require_json and not caps.supports_json_stream
    if (
        not caps.supports_native_system_prompt
        or not caps.supports_native_tool_allowlist
        or needs_output_contract_shim
    ):
        query = _shim_prompt(
            prompt=prompt,
            system_prompt=system_prompt,
            allowed_tools=(
                allowed_tools if not caps.supports_native_tool_allowlist else None
            ),
            require_json_output=needs_output_contract_shim,
        )

    if provider_id == "codex":
        cmd = [binary, "exec", "--model", model, query]
    elif provider_id == "omp":
        cmd = [binary, "-p", query, "--model", model, "--mode", "json"]
        if caps.supports_native_system_prompt:
            cmd.extend(["--system-prompt", system_prompt])
    else:
        cmd = [binary, "run", query, "--model", model, "--format", "json"]

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )


def run_agent_task(
    provider_id: str,
    model: str,
    system_prompt: str,
    prompt: str,
    cwd: Path,
    cfg: ProjectConfig,
    settings_file: Optional[Path] = None,
) -> subprocess.CompletedProcess[str]:
    """
    Run an autonomous coding session prompt across providers.
    """
    provider_id = normalize_provider_id(provider_id)
    binary = ensure_provider_binary_exists(provider_id, cfg)

    if provider_id == "claude":
        if settings_file is None:
            raise ValueError("settings_file is required for claude provider")
        return subprocess.run(
            [
                binary,
                "--dangerously-skip-permissions",
                "--model",
                model,
                "--settings",
                str(settings_file.resolve()),
                "--append-system-prompt",
                system_prompt,
            ],
            input=prompt,
            capture_output=True,
            text=True,
            cwd=str(cwd),
        )

    query = _shim_prompt(
        prompt=prompt,
        system_prompt=system_prompt,
        allowed_tools=None,
        require_json_output=False,
    )

    if provider_id == "codex":
        cmd = [binary, "exec", "--model", model, query]
    elif provider_id == "omp":
        cmd = [binary, "-p", query, "--model", model]
        if CAPABILITIES["omp"].supports_native_append_system_prompt:
            cmd.extend(["--append-system-prompt", system_prompt])
    else:
        cmd = [binary, "run", query, "--model", model]

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )
