#!/usr/bin/env python3
"""
Autonomous Coding Agent Demo
============================

A minimal harness demonstrating long-running autonomous coding with Claude.
This script implements the two-agent pattern (initializer + coding agent) and
incorporates all the strategies from the long-running agents guide.

Example Usage:
    # Auto-detect tech stack and write .env, then start coding:
    python acaps.py --project-dir ./my_project --configure

    # Start (or resume) using existing .env config:
    python acaps.py --project-dir ./my_project

    # Limit iterations for testing:
    python acaps.py --project-dir ./my_project --max-iterations 5
"""

import argparse
import asyncio
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


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    cfg = get_config()

    parser = argparse.ArgumentParser(
        description="Autonomous Coding Agent Demo - Long-running agent harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate prompts interactively from pasted text:
  python acaps.py --prompt

  # Generate prompts from a PRD file:
  python acaps.py --prompt --prompt-files ./my_prd.txt

  # Full pipeline: generate prompts → detect stack → run agents:
  python acaps.py --prompt --configure --project-dir ./my_project

  # First time — detect stack, write .env, then run:
  python acaps.py --project-dir ./my_project --configure

  # Resume or start with existing .env:
  python acaps.py --project-dir ./my_project

  # Override the model for this run only:
  python acaps.py --project-dir ./my_project --model claude-opus-4-6

  # Limit iterations for testing:
  python acaps.py --project-dir ./my_project --max-iterations 5

  # Regenerate .env after editing prompts/:
  python acaps.py --configure

Authentication:
  Run 'claude login' once to authenticate via the Claude Code CLI.
  Alternatively, set ANTHROPIC_API_KEY in your environment.
        """,
    )

    parser.add_argument(
        "--project-dir",
        type=Path,
        default=Path("./autonomous_demo_project"),
        help="Directory for the project (default: autonomous_demo_project). "
             "Relative paths are automatically placed under the PROJECT_DIR_PREFIX directory.",
    )

    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Maximum number of agent iterations (default: unlimited)",
    )

    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help=f"Claude model to use (default: {cfg.claude_model} from .env or CLAUDE_MODEL)",
    )

    parser.add_argument(
        "--configure",
        action="store_true",
        help="Run the configuration agent to detect the tech stack and write .env, "
             "then continue with the coding agents.",
    )

    parser.add_argument(
        "--configure-model",
        type=str,
        default=None,
        help=f"Model for the --configure agent (default: {cfg.configure_model} "
             f"from .env or CONFIGURE_MODEL)",
    )

    parser.add_argument(
        "--prompt",
        action="store_true",
        help="Launch the interactive prompt wizard to generate prompts/ files from your PRD.",
    )

    parser.add_argument(
        "--prompt-files",
        nargs="+",
        metavar="FILE",
        help="One or more file paths to use as source material (requires --prompt).",
    )

    parser.add_argument(
        "--prompt-overwrite",
        action="store_true",
        help="Overwrite existing prompts/ files (requires --prompt).",
    )

    parser.add_argument(
        "--agent-cli",
        type=str,
        choices=["claude", "codex", "omp", "opencode"],
        default=None,
        help=(
            "Agent CLI provider override for this run: "
            "claude|codex|omp|opencode."
        ),
    )

    parser.add_argument(
        "--save-agent-cli",
        action="store_true",
        help="Persist --agent-cli as AGENT_CLI_ID in .env for future runs.",
    )

    return parser.parse_args()


def main() -> None:
    """Main entry point."""
    args = parse_args()
    if args.save_agent_cli and not args.agent_cli:
        raise ValueError("--save-agent-cli requires --agent-cli")

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
            print("Prompt files generated. You can now run --configure to detect the stack.\n")
            # If --configure not also passed, stop here
            if not args.configure:
                return

        # Step 1: Run configuration agent if requested
        if args.configure:
            await run_configure(
                configure_model=args.configure_model or model,
                provider_id=provider_id,
            )
            # Reload config so the rest of the run uses freshly written .env
            cfg = reload_config()
            print("Configuration loaded. Starting coding agents...\n")
        else:
            cfg = get_config()

        # Step 3: Resolve project directory
        project_dir = args.project_dir
        prefix = cfg.project_dir_prefix.rstrip("/")
        if not str(project_dir).startswith(prefix + "/"):
            if project_dir.is_absolute():
                pass  # Use absolute paths as-is
            else:
                project_dir = Path(prefix) / project_dir

        # Step 4: Run the autonomous coding agent
        await run_autonomous_agent(
            project_dir=project_dir,
            model=model,
            max_iterations=args.max_iterations,
            provider_id=provider_id,
        )

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        print("To resume, run the same command again")
    except Exception as e:
        print(f"\nFatal error: {e}")
        raise


if __name__ == "__main__":
    main()
