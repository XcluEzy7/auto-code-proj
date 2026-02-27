#!/usr/bin/env python3
"""
Provider CLI resolution and env persistence tests.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from config import ProjectConfig, normalize_provider_id
from provider_cli import (
    has_env_var,
    resolve_model_for_run,
    resolve_provider_for_run,
    upsert_env_var,
)


class TestProviderConfig(unittest.TestCase):
    def test_normalize_provider_id_defaults_to_claude(self):
        self.assertEqual(normalize_provider_id(None), "claude")
        self.assertEqual(normalize_provider_id(""), "claude")
        self.assertEqual(normalize_provider_id("unknown"), "claude")
        self.assertEqual(normalize_provider_id("CoDeX"), "codex")

    def test_upsert_env_var_and_has_env_var(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            upsert_env_var("AGENT_CLI_ID", "codex", env_path)
            self.assertTrue(has_env_var("AGENT_CLI_ID", env_path))
            self.assertIn("AGENT_CLI_ID=codex", env_path.read_text(encoding="utf-8"))

            upsert_env_var("AGENT_CLI_ID", "omp", env_path)
            self.assertIn("AGENT_CLI_ID=omp", env_path.read_text(encoding="utf-8"))

    def test_resolve_provider_override_and_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            cfg = ProjectConfig(agent_cli_id="claude")
            provider = resolve_provider_for_run(
                cfg=cfg,
                cli_override="opencode",
                save_override=True,
                env_path=env_path,
            )
            self.assertEqual(provider, "opencode")
            self.assertIn(
                "AGENT_CLI_ID=opencode", env_path.read_text(encoding="utf-8")
            )

    def test_resolve_provider_first_run_interactive(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / ".env"
            cfg = ProjectConfig(agent_cli_id="claude")
            with (
                mock.patch("provider_cli.sys.stdin.isatty", return_value=True),
                mock.patch("provider_cli.sys.stdout.isatty", return_value=True),
                mock.patch("builtins.input", return_value="2"),
            ):
                provider = resolve_provider_for_run(
                    cfg=cfg,
                    cli_override=None,
                    save_override=False,
                    env_path=env_path,
                )
            self.assertEqual(provider, "codex")
            self.assertIn("AGENT_CLI_ID=codex", env_path.read_text(encoding="utf-8"))

    def test_resolve_model_defaults_non_interactive(self):
        cfg = ProjectConfig(agent_cli_model_omp="claude-sonnet-4-5")
        with (
            mock.patch("provider_cli.sys.stdin.isatty", return_value=False),
            mock.patch("provider_cli.sys.stdout.isatty", return_value=False),
            mock.patch("provider_cli.list_provider_models", return_value=["gpt-5.1"]),
        ):
            model = resolve_model_for_run(
                provider_id="omp",
                cfg=cfg,
                cli_override=None,
            )
        self.assertEqual(model, "claude-sonnet-4-5")

    def test_resolve_model_interactive_choice(self):
        cfg = ProjectConfig(agent_cli_model_omp="claude-sonnet-4-5")
        with (
            mock.patch("provider_cli.sys.stdin.isatty", return_value=True),
            mock.patch("provider_cli.sys.stdout.isatty", return_value=True),
            mock.patch("provider_cli.list_provider_models", return_value=["gpt-5.1"]),
            mock.patch("builtins.input", return_value="2"),
        ):
            model = resolve_model_for_run(
                provider_id="omp",
                cfg=cfg,
                cli_override=None,
            )
        self.assertEqual(model, "gpt-5.1")

    def test_resolve_model_cli_override_wins(self):
        cfg = ProjectConfig(agent_cli_model_omp="claude-sonnet-4-5")
        model = resolve_model_for_run(
            provider_id="omp",
            cfg=cfg,
            cli_override="my-custom-model",
        )
        self.assertEqual(model, "my-custom-model")


if __name__ == "__main__":
    unittest.main()
