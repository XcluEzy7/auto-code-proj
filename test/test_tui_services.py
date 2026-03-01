#!/usr/bin/env python3
"""Tests for TUI service helpers."""

import unittest
from pathlib import Path

from tui_core import PromptFlowPhase
from tui_services import (
    build_handoff_command,
    compute_flow_completion,
)


class TestTuiServices(unittest.TestCase):
    def test_build_handoff_command_includes_expected_flags(self):
        cmd = build_handoff_command(
            project_dir=Path("generations/demo"),
            provider_id="codex",
            model="gpt-5-codex",
        )
        self.assertEqual(
            cmd,
            [
                "uv",
                "run",
                "python3",
                "acaps.py",
                "--project-dir",
                "generations/demo",
                "--agent-cli",
                "codex",
                "--model",
                "gpt-5-codex",
            ],
        )

    def test_compute_flow_completion_uses_phase_weights(self):
        percent = compute_flow_completion(PromptFlowPhase.GENERATE)
        # ANALYZE (15) + QA (15) + GENERATE (35) = 65
        self.assertEqual(percent, 65)

    def test_compute_flow_completion_caps_at_100(self):
        percent = compute_flow_completion(PromptFlowPhase.HANDOFF)
        self.assertEqual(percent, 100)


if __name__ == "__main__":
    unittest.main()
