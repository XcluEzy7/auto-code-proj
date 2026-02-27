#!/usr/bin/env python3
"""
Prompt generation retry behavior tests.
Run with: python test_prompter_retry.py
"""

import subprocess
import unittest
from unittest import mock

from prompter import run_generation_session


class TestPrompterRetry(unittest.IsolatedAsyncioTestCase):
    async def test_retry_once_then_success(self):
        first = subprocess.CompletedProcess(
            args=["claude"],
            returncode=0,
            stdout="```json\n{\"app_spec\":\"<x>\",\"initializer_prompt\": \"oops\"\n```",
            stderr="",
        )
        second = subprocess.CompletedProcess(
            args=["claude"],
            returncode=0,
            stdout=(
                '{"app_spec":"<project_specification/>",'
                '"initializer_prompt":"# init",'
                '"coding_prompt":"# code"}'
            ),
            stderr="",
        )

        with mock.patch("prompter.subprocess.run", side_effect=[first, second]) as run_mock:
            parsed = await run_generation_session("Build app", [], "claude-sonnet-4-6")
            self.assertEqual(parsed["coding_prompt"], "# code")
            self.assertEqual(run_mock.call_count, 2)

    async def test_retry_once_then_failure(self):
        first = subprocess.CompletedProcess(
            args=["claude"],
            returncode=0,
            stdout='{"app_spec":"x","initializer_prompt":"y"',
            stderr="",
        )
        second = subprocess.CompletedProcess(
            args=["claude"],
            returncode=0,
            stdout='{"app_spec":"x"}',
            stderr="",
        )

        with mock.patch("prompter.subprocess.run", side_effect=[first, second]):
            with self.assertRaises(RuntimeError) as ctx:
                await run_generation_session("Build app", [], "claude-sonnet-4-6")
            self.assertIn("Generation failed after one retry", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
