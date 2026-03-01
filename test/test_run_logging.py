#!/usr/bin/env python3
"""Tests for structured run logging and handoff stream tee."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from run_logging import RunLogger
from handoff import run_handoff_command_with_logging


class TestRunLogging(unittest.TestCase):
    def test_run_logger_writes_jsonl_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = RunLogger.create(
                enabled=True,
                base_dir=Path(tmp),
                provider="codex",
                model="gpt-5-codex",
                project_dir=Path("."),
            )
            self.assertTrue(logger.enabled)
            self.assertIsNotNone(logger.log_file)
            assert logger.log_file is not None
            self.assertIn("codex", logger.log_file.name)
            self.assertIn("gpt-5-codex", logger.log_file.name)

            logger.log_event(
                phase="analyze",
                event_type="stream",
                message="analysis line",
                stream="stdout",
            )

            lines = logger.log_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            event = json.loads(lines[0])
            self.assertEqual(event["phase"], "analyze")
            self.assertEqual(event["event_type"], "stream")
            self.assertEqual(event["stream"], "stdout")
            self.assertEqual(event["message"], "analysis line")
            self.assertEqual(event["provider"], "codex")

    def test_run_logger_disabled_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = RunLogger.create(
                enabled=False,
                base_dir=Path(tmp),
                provider="codex",
                model="gpt-5-codex",
                project_dir=Path("."),
            )
            self.assertFalse(logger.enabled)
            logger.log_event(phase="system", event_type="lifecycle", message="ignored")
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_handoff_stream_logs_stdout_and_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = RunLogger.create(
                enabled=True,
                base_dir=Path(tmp),
                provider="codex",
                model="gpt-5-codex",
                project_dir=Path("."),
            )
            assert logger.log_file is not None

            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                return_code = run_handoff_command_with_logging(
                    ["python3", "-c", "import sys; print('out-line'); print('err-line', file=sys.stderr)"],
                    logger,
                )

            self.assertEqual(return_code, 0)
            events = [
                json.loads(line)
                for line in logger.log_file.read_text(encoding="utf-8").splitlines()
            ]
            messages = [event["message"] for event in events]
            self.assertIn("out-line", messages)
            self.assertIn("err-line", messages)
            self.assertIn("handoff_started", messages)
            self.assertIn("handoff_finished", messages)


if __name__ == "__main__":
    unittest.main()
