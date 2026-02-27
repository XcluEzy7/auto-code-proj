"""
Claude CLI Settings Configuration
==================================

Functions for creating settings files consumed by the Claude CLI via --settings.
"""

import json
from pathlib import Path

from config import get_config


# Puppeteer MCP tools for browser automation
PUPPETEER_TOOLS = [
    "mcp__puppeteer__puppeteer_navigate",
    "mcp__puppeteer__puppeteer_screenshot",
    "mcp__puppeteer__puppeteer_click",
    "mcp__puppeteer__puppeteer_fill",
    "mcp__puppeteer__puppeteer_select",
    "mcp__puppeteer__puppeteer_hover",
    "mcp__puppeteer__puppeteer_evaluate",
]


def create_settings(project_dir: Path) -> Path:
    """
    Write security settings JSON for the CLI to read via --settings.

    Args:
        project_dir: Directory for the project

    Returns:
        Path to the settings file
    """
    cfg = get_config()
    security_settings = {
        "sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True},
        "permissions": {
            "defaultMode": "acceptEdits",
            "allow": [
                "Read(./**)",
                "Write(./**)",
                "Edit(./**)",
                "Glob(./**)",
                "Grep(./**)",
                "Bash(*)",
                *PUPPETEER_TOOLS,
            ],
        },
    }

    project_dir.mkdir(parents=True, exist_ok=True)
    settings_file = project_dir / cfg.settings_filename
    settings_file.write_text(json.dumps(security_settings, indent=2))

    print(f"Created security settings at {settings_file}")
    print("   - Sandbox enabled (OS-level bash isolation)")
    print(f"   - Filesystem restricted to: {project_dir.resolve()}")
    print("   - MCP servers: puppeteer (browser automation)")
    print()

    return settings_file
