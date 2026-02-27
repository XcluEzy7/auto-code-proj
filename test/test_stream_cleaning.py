#!/usr/bin/env python3
"""Tests for provider stream cleaning."""

import unittest

from stream_cleaning import StreamCleaner


class TestStreamCleaner(unittest.TestCase):
    def test_omp_assistant_text_filters_thinking(self):
        cleaner = StreamCleaner(mode="assistant_text", show_thinking=False)
        raw = (
            '{"type":"message_update","assistantMessageEvent":{"type":"thinking_delta",'
            '"delta":"internal"},"message":{"role":"assistant"}}'
        )
        self.assertEqual(cleaner.ingest("omp", "stdout", raw), [])

    def test_omp_assistant_text_emits_text_delta(self):
        cleaner = StreamCleaner(mode="assistant_text", show_thinking=False)
        raw = (
            '{"type":"message_update","assistantMessageEvent":{"type":"text_delta",'
            '"delta":"Hello"}}'
        )
        self.assertEqual(cleaner.ingest("omp", "stdout", raw), ["Hello"])

    def test_omp_compact_mode_emits_marker(self):
        cleaner = StreamCleaner(mode="compact", show_thinking=False)
        raw = '{"type":"message_end"}'
        self.assertEqual(cleaner.ingest("omp", "stdout", raw), ["[message_end]"])

    def test_non_omp_passthrough(self):
        cleaner = StreamCleaner(mode="assistant_text", show_thinking=False)
        self.assertEqual(cleaner.ingest("claude", "stdout", "plain text"), ["plain text"])

    def test_unknown_json_passthrough(self):
        cleaner = StreamCleaner(mode="assistant_text", show_thinking=False)
        self.assertEqual(cleaner.ingest("omp", "stdout", "{not json"), ["{not json"])


if __name__ == "__main__":
    unittest.main()
