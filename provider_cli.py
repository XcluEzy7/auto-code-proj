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
import re
import threading
import queue
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

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


StreamCallback = Callable[[str, str], None]


def _run_command_with_streaming(
    cmd: list[str],
    cwd: Path,
    input_text: str | None = None,
    on_stream: StreamCallback | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    Run a command and optionally stream stdout/stderr lines to a callback.

    Callback signature: callback(stream_name, line_text)
    where stream_name is "stdout" or "stderr".
    """
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(cwd),
        bufsize=1,
    )

    if input_text is not None and proc.stdin is not None:
        proc.stdin.write(input_text)
        proc.stdin.close()

    q: queue.Queue[tuple[str, str | None]] = queue.Queue()
    out_lines: list[str] = []
    err_lines: list[str] = []

    def _reader(stream_name: str, handle: Optional[object]) -> None:
        if handle is None:
            q.put((stream_name, None))
            return
        for line in handle:
            q.put((stream_name, line))
        q.put((stream_name, None))

    threads = [
        threading.Thread(
            target=_reader,
            args=("stdout", proc.stdout),
            daemon=True,
        ),
        threading.Thread(
            target=_reader,
            args=("stderr", proc.stderr),
            daemon=True,
        ),
    ]
    for t in threads:
        t.start()

    completed_streams = 0
    while completed_streams < 2:
        stream_name, line = q.get()
        if line is None:
            completed_streams += 1
            continue
        if stream_name == "stdout":
            out_lines.append(line)
        else:
            err_lines.append(line)
        if on_stream is not None:
            on_stream(stream_name, line.rstrip("\n"))

    returncode = proc.wait()
    return subprocess.CompletedProcess(
        args=cmd,
        returncode=returncode,
        stdout="".join(out_lines),
        stderr="".join(err_lines),
    )


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


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from terminal output."""
    return re.sub(r"\x1B\[[0-?]*[ -/]*[@-~]", "", text)


def _parse_models_from_output(output: str) -> list[str]:
    """Extract likely model IDs from CLI output."""
    models: list[str] = []
    seen: set[str] = set()
    for raw_line in _strip_ansi(output).splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Most CLIs print model IDs as the first column/token.
        token = line.split()[0].strip(",")
        lowered = token.lower()
        if lowered in {"usage:", "error", "error:", "warning", "warning:", "commands:"}:
            continue
        if token.startswith(("-", "=", "#", "[")):
            continue
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", token):
            continue
        if "/" not in token and "-" not in token:
            continue

        if token not in seen:
            seen.add(token)
            models.append(token)
    return models


def list_provider_models(
    provider_id: str,
    cfg: ProjectConfig,
    cwd: Optional[Path] = None,
) -> list[str]:
    """
    Query a provider CLI for available models. Returns an empty list if unsupported.
    """
    provider_id = normalize_provider_id(provider_id)
    binary = ensure_provider_binary_exists(provider_id, cfg)

    if provider_id == "omp":
        cmd = [binary, "--list-models"]
    elif provider_id == "opencode":
        cmd = [binary, "models"]
    else:
        # Claude/Codex do not expose a simple non-interactive model list command.
        return []

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd or Path.cwd()),
    )
    if result.returncode != 0 and not result.stdout.strip():
        return []
    return _parse_models_from_output(result.stdout)


def _interactive_model_choice(
    provider_id: str,
    default_model: str,
    discovered_models: list[str],
) -> str:
    """Prompt user to select a model, with optional discovered model choices."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return default_model

    options: list[str] = []
    seen: set[str] = set()
    for value in [default_model, *discovered_models]:
        model = value.strip()
        if model and model not in seen:
            seen.add(model)
            options.append(model)

    print(f"\nSelect model for provider '{provider_id}':")
    if options:
        for idx, value in enumerate(options, start=1):
            marker = " (default)" if value == default_model else ""
            print(f"  {idx}. {value}{marker}")
        print("  m. Enter a custom model ID")
    else:
        print("  (No model list discovered. You can enter a custom model ID.)")

    while True:
        if options:
            choice = input(f"Choose [Enter={default_model}]: ").strip()
            if not choice:
                return default_model
            if choice.lower() == "m":
                custom = input("Model ID: ").strip()
                return custom or default_model
            if choice.isdigit():
                idx = int(choice)
                if 1 <= idx <= len(options):
                    return options[idx - 1]
            # Allow direct model ID entry at the prompt.
            return choice

        custom = input(f"Model ID [Enter={default_model}]: ").strip()
        return custom or default_model


def resolve_model_for_run(
    provider_id: str,
    cfg: ProjectConfig,
    cli_override: Optional[str],
) -> str:
    """
    Resolve model for this run.
    Priority: explicit --model > interactive pick (TTY) > provider default from config.
    """
    if cli_override and cli_override.strip():
        return cli_override.strip()

    default_model = provider_default_model(provider_id, cfg)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return default_model

    discovered = list_provider_models(provider_id, cfg)
    return _interactive_model_choice(provider_id, default_model, discovered)


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
    stream_callback: StreamCallback | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    Run a one-shot prompt task across providers (analysis/config/generation).
    """
    provider_id = normalize_provider_id(provider_id)
    binary = ensure_provider_binary_exists(provider_id, cfg)
    caps = CAPABILITIES[provider_id]
    require_json = cfg.agent_cli_require_json_output

    if provider_id == "claude":
        cmd = [
            binary,
            "-p",
            "--model",
            model,
            "--allowedTools",
            allowed_tools,
            "--system-prompt",
            system_prompt,
        ]
        if stream_callback is None:
            return subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                cwd=str(cwd),
            )
        return _run_command_with_streaming(
            cmd=cmd,
            cwd=cwd,
            input_text=prompt,
            on_stream=stream_callback,
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

    if stream_callback is None:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(cwd),
        )

    return _run_command_with_streaming(
        cmd=cmd,
        cwd=cwd,
        on_stream=stream_callback,
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
