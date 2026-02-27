#!/usr/bin/env python3
"""Autonomy override tests for generated prompts."""

import unittest

from prompter import apply_autonomy_override


class TestPrompterAutonomy(unittest.TestCase):
    def test_inserts_autonomy_contract_once(self):
        base = "# Coding Prompt\nDo the work."
        once = apply_autonomy_override(base, enabled=True)
        twice = apply_autonomy_override(once, enabled=True)
        self.assertIn("## Autonomous Execution Contract", once)
        self.assertEqual(once, twice)

    def test_no_insert_when_disabled(self):
        base = "# Coding Prompt\nDo the work."
        out = apply_autonomy_override(base, enabled=False)
        self.assertEqual(base, out)


if __name__ == "__main__":
    unittest.main()
