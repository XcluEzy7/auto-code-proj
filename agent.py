"""
Agent Session Logic
===================

Core agent interaction functions for running autonomous coding sessions.
Uses subprocess piping to the Claude CLI instead of the SDK.
"""

import asyncio
from pathlib import Path
from typing import Optional

from client import create_settings
from config import get_config
from provider_cli import run_agent_task
from progress import print_session_header, print_progress_summary
from prompts import get_initializer_prompt, get_coding_prompt, copy_spec_to_project


def run_agent_session(
    prompt: str,
    project_dir: Path,
    model: str,
    settings_file: Path,
    provider_id: str,
) -> tuple[str, str]:
    """
    Run a single agent session by piping the prompt to the Claude CLI via stdin.

    Args:
        prompt: The prompt to send
        project_dir: Project directory path
        model: Claude model to use
        settings_file: Path to the settings JSON file
        provider_id: Selected CLI provider ID

    Returns:
        (status, response_text) where status is:
        - "continue" if session completed successfully
        - "error" if an error occurred
    """
    cfg = get_config()

    print(f"Sending prompt to {provider_id} CLI...\n")

    result = run_agent_task(
        provider_id=provider_id,
        model=model,
        system_prompt=cfg.agent_system_prompt,
        prompt=prompt,
        cwd=project_dir.resolve(),
        cfg=cfg,
        settings_file=settings_file,
    )

    if result.returncode != 0:
        error_msg = result.stderr[:500] if result.stderr else "(no stderr)"
        print(f"[Error] {error_msg}")
        return "error", result.stderr

    print(result.stdout)
    print("\n" + "-" * 70 + "\n")
    return "continue", result.stdout


async def run_autonomous_agent(
    project_dir: Path,
    model: str,
    max_iterations: Optional[int] = None,
    provider_id: str = "claude",
) -> None:
    """
    Run the autonomous agent loop.

    Args:
        project_dir: Directory for the project
        model: Claude model to use
        max_iterations: Maximum number of iterations (None for unlimited)
    """
    cfg = get_config()

    print("\n" + "=" * 70)
    print("  AUTONOMOUS CODING AGENT DEMO")
    print("=" * 70)
    print(f"\nProject directory: {project_dir}")
    print(f"Model: {model}")
    print(f"Provider: {provider_id}")
    if max_iterations:
        print(f"Max iterations: {max_iterations}")
    else:
        print("Max iterations: Unlimited (will run until completion)")
    print()

    # Create project directory
    project_dir.mkdir(parents=True, exist_ok=True)

    # Check if this is a fresh start or continuation
    tests_file = project_dir / cfg.feature_list_file
    is_first_run = not tests_file.exists()

    if is_first_run:
        print("Fresh start - will use initializer agent")
        print()
        print("=" * 70)
        print("  NOTE: First session takes 10-20+ minutes!")
        print("  The agent is generating 200 detailed test cases.")
        print("  This may appear to hang - it's working. Watch for output.")
        print("=" * 70)
        print()
        copy_spec_to_project(project_dir)
    else:
        print("Continuing existing project")
        print_progress_summary(project_dir)

    # Create settings file once for all sessions
    settings_file = create_settings(project_dir)

    # Main loop
    iteration = 0

    while True:
        iteration += 1

        # Check max iterations
        if max_iterations and iteration > max_iterations:
            print(f"\nReached max iterations ({max_iterations})")
            print("To continue, run the script again without --max-iterations")
            break

        # Print session header
        print_session_header(iteration, is_first_run)

        # Choose prompt based on session type
        if is_first_run:
            prompt = get_initializer_prompt()
            is_first_run = False  # Only use initializer once
        else:
            prompt = get_coding_prompt()

        # Run session
        status, _ = run_agent_session(
            prompt=prompt,
            project_dir=project_dir,
            model=model,
            settings_file=settings_file,
            provider_id=provider_id,
        )

        # Handle status
        if status == "continue":
            print(f"\nAgent will auto-continue in {cfg.auto_continue_delay}s...")
            print_progress_summary(project_dir)
            await asyncio.sleep(cfg.auto_continue_delay)

        elif status == "error":
            print("\nSession encountered an error")
            print("Will retry with a fresh session...")
            await asyncio.sleep(cfg.auto_continue_delay)

        # Small delay between sessions
        if max_iterations is None or iteration < max_iterations:
            print("\nPreparing next session...\n")
            await asyncio.sleep(1)

    # Final summary
    print("\n" + "=" * 70)
    print("  SESSION COMPLETE")
    print("=" * 70)
    print(f"\nProject directory: {project_dir}")
    print_progress_summary(project_dir)

    # Print instructions for running the generated application
    print("\n" + "-" * 70)
    print("  TO RUN THE GENERATED APPLICATION:")
    print("-" * 70)
    print(f"\n  cd {project_dir.resolve()}")
    print(f"  ./{cfg.init_script_name}           # Run the setup script")
    print("  # Or manually:")
    print(f"  {cfg.dev_server_cmd}")
    print(f"\n  Then open {cfg.dev_server_url} (or check {cfg.init_script_name} for the URL)")
    print("-" * 70)

    print("\nDone!")
