"""
Prompt Loading Utilities
========================

Functions for loading prompt templates from the prompts directory.
"""

import shutil
from pathlib import Path

from config import get_config


def _prompts_dir() -> Path:
    """Return the prompts directory from config."""
    return Path(__file__).parent / get_config().prompts_dir


def load_prompt(name: str) -> str:
    """Load a prompt template from the prompts directory."""
    prompt_path = _prompts_dir() / f"{name}.md"
    return prompt_path.read_text()


def get_initializer_prompt() -> str:
    """Load the initializer prompt."""
    return load_prompt(get_config().initializer_prompt_name)


def get_coding_prompt() -> str:
    """Load the coding agent prompt."""
    return load_prompt(get_config().coding_prompt_name)


def copy_spec_to_project(project_dir: Path) -> None:
    """Copy the app spec file into the project directory for the agent to read."""
    cfg = get_config()
    spec_source = _prompts_dir() / cfg.app_spec_filename
    spec_dest = project_dir / cfg.app_spec_filename
    if not spec_dest.exists():
        shutil.copy(spec_source, spec_dest)
        print(f"Copied {cfg.app_spec_filename} to project directory")
