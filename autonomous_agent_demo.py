#!/usr/bin/env python3
"""
Autonomous Coding Agent Demo
============================

A minimal harness demonstrating long-running autonomous coding with Claude.
This script implements the two-agent pattern (initializer + coding agent) and
incorporates all the strategies from the long-running agents guide.

Example Usage:
    # Auto-detect tech stack and write .env, then start coding:
    python autonomous_agent_demo.py --project-dir ./my_project --configure

    # Start (or resume) using existing .env config:
    python autonomous_agent_demo.py --project-dir ./my_project

    # Limit iterations for testing:
    python autonomous_agent_demo.py --project-dir ./my_project --max-iterations 5
"""

import argparse
import asyncio
import os
from pathlib import Path

from agent import run_autonomous_agent
from config import get_config, reload_config
from configure import run_configure


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    cfg = get_config()

    parser = argparse.ArgumentParser(
        description="Autonomous Coding Agent Demo - Long-running agent harness",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # First time — detect stack, write .env, then run:
  python autonomous_agent_demo.py --project-dir ./my_project --configure

  # Resume or start with existing .env:
  python autonomous_agent_demo.py --project-dir ./my_project

  # Override the model for this run only:
  python autonomous_agent_demo.py --project-dir ./my_project --model claude-opus-4-6

  # Limit iterations for testing:
  python autonomous_agent_demo.py --project-dir ./my_project --max-iterations 5

  # Regenerate .env after editing prompts/:
  python autonomous_agent_demo.py --configure

Environment Variables:
  ANTHROPIC_API_KEY    Your Anthropic API key (required)
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

    return parser.parse_args()


def main() -> None:
    """Main entry point."""
    args = parse_args()

    # Check for API key
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY environment variable not set")
        print("\nGet your API key from: https://console.anthropic.com/")
        print("\nThen set it:")
        print("  export ANTHROPIC_API_KEY='your-api-key-here'")
        return

    async def _run() -> None:
        # Step 1: Run configuration agent if requested
        if args.configure:
            await run_configure(configure_model=args.configure_model)
            # Reload config so the rest of the run uses freshly written .env
            cfg = reload_config()
            print("Configuration loaded. Starting coding agents...\n")
        else:
            cfg = get_config()

        # Step 2: Resolve model (CLI arg > .env > default)
        model = args.model or cfg.claude_model

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
