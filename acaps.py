#!/usr/bin/env python3
"""
Autonomous Coding Agent Demo
============================

A minimal harness demonstrating long-running autonomous coding with Claude.
"""

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

from agent import run_autonomous_agent
from config import get_config, reload_config
from configure import run_configure
from provider_cli import (
    print_degraded_capability_warning,
    resolve_model_for_run,
    resolve_provider_for_run,
)
from prompter import run_prompter


def launch_tui(mode: str, args: argparse.Namespace) -> int:
    """Launch the OpenTui frontend with the given mode."""
    # Check for bun
    try:
        subprocess.run(["bun", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Error: Bun is required to run the TUI.", file=sys.stderr)
        print("Install it from https://bun.sh", file=sys.stderr)
        return 1

    # Set environment variables for the TUI
    env = os.environ.copy()
    env["ACAP_TUI_MODE"] = mode
    if args.project_dir:
        env["ACAP_PROJECT_DIR"] = str(args.project_dir)
    if args.prompt_files:
        env["ACAP_PROMPT_FILES"] = " ".join(args.prompt_files)
    if args.agent_cli:
        env["ACAP_PROVIDER"] = args.agent_cli
    if args.model:
        env["ACAP_MODEL"] = args.model
    if args.prompt_overwrite:
        env["ACAP_OVERWRITE"] = "1"

    # Launch the TUI
    opentui_dir = Path(__file__).parent / "opentui"
    cmd = ["bun", "run", "index.ts"]

    return subprocess.run(cmd, cwd=opentui_dir, env=env).returncode


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser with TUI subcommands and legacy options."""
    cfg = get_config()

    parser = argparse.ArgumentParser(
        description="Autonomous Coding Agent Demo - Long-running agent harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
TUI Mode (New OpenTui interface):
  acaps.py tui run              Full end-to-end prep flow
  acaps.py tui prompt           Prompt wizard only
  acaps.py tui configure        Configure only

CLI Mode (Legacy):
  acaps.py --prompt             Generate prompts interactively
  acaps.py --prompt --configure Full pipeline
  acaps.py --project-dir DIR    Run coding agents

Authentication:
  Run 'claude login' once to authenticate.
        """,
    )

    # Create subparsers for tui command
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # TUI subcommand
    tui_parser = subparsers.add_parser("tui", help="Launch OpenTui interface (requires Bun)")
    tui_subparsers = tui_parser.add_subparsers(dest="tui_command", required=True, help="TUI mode")

    # TUI run (full flow)
    tui_run = tui_subparsers.add_parser("run", help="Full end-to-end prep flow")
    _add_common_args(tui_run)

    # TUI prompt-only
    tui_prompt = tui_subparsers.add_parser("prompt", help="Prompt wizard only")
    _add_common_args(tui_prompt)

    # TUI configure-only
    tui_configure = tui_subparsers.add_parser("configure", help="Configure only")
    _add_common_args(tui_configure)

    # Legacy mode arguments (at root level)
    _add_common_args(parser)
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Maximum number of agent iterations (default: unlimited)",
    )
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Run the configuration agent to detect tech stack and write .env",
    )
    parser.add_argument(
        "--configure-model",
        type=str,
        default=None,
        help=f"Model for configure agent (default: {cfg.configure_model})",
    )
    parser.add_argument(
        "--prompt",
        action="store_true",
        help="Launch interactive prompt wizard",
    )
    parser.add_argument(
        "--save-agent-cli",
        action="store_true",
        help="Persist --agent-cli to .env",
    )

    return parser


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add arguments common to all modes."""
    cfg = get_config()
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path("./autonomous_demo_project"),
        help="Directory for the project",
    )
    parser.add_argument(
        "--prompt-files",
        nargs="+",
        metavar="FILE",
        help="File(s) to use as source material",
    )
    parser.add_argument(
        "--agent-cli",
        type=str,
        choices=["claude", "codex", "omp", "opencode"],
        default=None,
        help="Agent CLI provider override",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help=f"Model to use (default: {cfg.claude_model})",
    )
    parser.add_argument(
        "--prompt-overwrite",
        action="store_true",
        help="Overwrite existing prompts/ files",
    )


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    # Handle TUI mode
    if args.command == "tui":
        return launch_tui(args.tui_command, args)

    # Legacy CLI mode
    if args.save_agent_cli and not args.agent_cli:
        print("Error: --save-agent-cli requires --agent-cli", file=sys.stderr)
        return 1

    async def _run() -> None:
        cfg = get_config()
        env_path = Path(__file__).parent / ".env"
        provider_id = resolve_provider_for_run(
            cfg=cfg,
            cli_override=args.agent_cli,
            save_override=args.save_agent_cli,
            env_path=env_path,
        )
        cfg = reload_config()

        print(f"Agent CLI provider: {provider_id}")
        print_degraded_capability_warning(provider_id, cfg)
        model = resolve_model_for_run(
            provider_id=provider_id,
            cfg=cfg,
            cli_override=args.model,
        )
        print(f"Selected model: {model}")

        # Step 0: Run prompt wizard if requested
        if args.prompt:
            success = await run_prompter(
                prompt_files=args.prompt_files,
                analysis_model=model,
                generation_model=model,
                overwrite=args.prompt_overwrite,
                provider_id=provider_id,
            )
            if not success:
                return
            print("Prompt files generated. Run --configure to detect the stack.\n")
            if not args.configure:
                return

        # Step 1: Run configuration
        if args.configure:
            await run_configure(
                configure_model=args.configure_model or model,
                provider_id=provider_id,
            )
            cfg = reload_config()
            print("Configuration loaded. Starting coding agents...\n")
        else:
            cfg = get_config()

        # Step 3: Resolve project directory
        project_dir = args.project_dir
        prefix = cfg.project_dir_prefix.rstrip("/")
        if not str(project_dir).startswith(prefix + "/"):
            if not project_dir.is_absolute():
                project_dir = Path(prefix) / project_dir

        # Step 4: Run autonomous agent
        await run_autonomous_agent(
            project_dir=project_dir,
            model=model,
            max_iterations=args.max_iterations,
            provider_id=provider_id,
        )

    try:
        asyncio.run(_run())
        return 0
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        print("To resume, run the same command again")