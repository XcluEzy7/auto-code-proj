#!/usr/bin/env python3
"""Tests for latest run log helper."""

import tempfile
import time
import unittest
from pathlib import Path

from latest_run_log import find_latest_run_log, read_last_lines


class TestLatestRunLog(unittest.TestCase):
    def test_find_latest_run_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            older = log_dir / "old.jsonl"
            newer = log_dir / "new.jsonl"
            older.write_text("old\n", encoding="utf-8")
            time.sleep(0.01)
            newer.write_text("new\n", encoding="utf-8")

            latest = find_latest_run_log(log_dir)
            self.assertEqual(latest, newer)

    def test_find_latest_run_log_ignores_non_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            (log_dir / "note.txt").write_text("x\n", encoding="utf-8")
            latest = find_latest_run_log(log_dir)
            self.assertIsNone(latest)

    def test_read_last_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run.jsonl"
            path.write_text("a\nb\nc\nd\n", encoding="utf-8")
            self.assertEqual(read_last_lines(path, 2), ["c", "d"])
            self.assertEqual(read_last_lines(path, 0), [])


if __name__ == "__main__":
    unittest.main()

