#!/usr/bin/env python3
"""
JSON extraction tests for configure.extract_json_from_text.
Run with: python test_json_extraction.py
"""

import json
import unittest

from configure import extract_json_from_text


class TestJsonExtraction(unittest.TestCase):
    def test_direct_json_parse(self):
        text = '{"framework":"django","package_manager":"pip"}'
        parsed = extract_json_from_text(text)
        self.assertEqual(parsed["framework"], "django")

    def test_fenced_json_with_xml_payload(self):
        payload = {
            "app_spec": "<?xml version=\"1.0\"?>\n<project_specification>{voice}</project_specification>",
            "initializer_prompt": "# init\nline2",
            "coding_prompt": "# code\nline2",
        }
        text = "```json\n" + json.dumps(payload) + "\n```"
        parsed = extract_json_from_text(
            text,
            required_keys={"app_spec", "initializer_prompt", "coding_prompt"},
            exact_keys=True,
        )
        self.assertIn("<project_specification>", parsed["app_spec"])

    def test_scans_past_invalid_object_to_valid_object(self):
        payload = {
            "app_spec": "<project_specification>{a}</project_specification>",
            "initializer_prompt": "init",
            "coding_prompt": "code",
        }
        text = 'noise {"broken": } more noise\n' + json.dumps(payload)
        parsed = extract_json_from_text(
            text,
            required_keys={"app_spec", "initializer_prompt", "coding_prompt"},
            exact_keys=True,
        )
        self.assertEqual(parsed["coding_prompt"], "code")

    def test_required_keys_validation_error(self):
        text = '{"app_spec":"x","initializer_prompt":"y"}'
        with self.assertRaises(ValueError) as ctx:
            extract_json_from_text(
                text,
                required_keys={"app_spec", "initializer_prompt", "coding_prompt"},
                exact_keys=True,
            )
        self.assertIn("Missing required keys", str(ctx.exception))

    def test_truncated_json_has_diagnostics(self):
        text = '{"app_spec":"x","initializer_prompt":"y"'
        with self.assertRaises(ValueError) as ctx:
            extract_json_from_text(text)
        self.assertIn("Parsing stages attempted", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
