import os
import sys
import unittest

SIDE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sidecars", "task_monitor"))
if SIDE_DIR not in sys.path:
    sys.path.insert(0, SIDE_DIR)

from core.formatting import (
    clean_user_prompt,
    extract_generic_body,
    extract_workspace_name,
    format_duration,
    format_tokens,
    parse_iso,
    parse_step_exit_code,
)


class TestFormattingUtilities(unittest.TestCase):
    def test_extract_workspace_name(self):
        home_uri = "file://" + os.path.expanduser("~")
        self.assertEqual(extract_workspace_name(home_uri), "Default workspace")
        self.assertEqual(extract_workspace_name("file:///Users"), "Default workspace")
        self.assertEqual(
            extract_workspace_name('["file:///workspace/antigravity%20pulse"]'),
            "antigravity pulse",
        )
        self.assertEqual(extract_workspace_name(""), "Default workspace")

    def test_format_tokens_and_duration(self):
        self.assertEqual(format_tokens(500), "500")
        self.assertEqual(format_tokens(1500), "1.5k")
        self.assertEqual(format_tokens(2_500_000), "2.5M")
        self.assertEqual(format_tokens(1_250_000_000), "1.2B")
        self.assertEqual(format_duration(45), "45s")
        self.assertEqual(format_duration(125), "2m5s")
        self.assertEqual(format_duration(3720), "1h2m")

    def test_parse_iso_handles_z_and_sqlite_fmt(self):
        dt = parse_iso("2026-11-23T06:00:00Z")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        dt2 = parse_iso("2026-11-23 06:00:00")
        self.assertIsNotNone(dt2)
        self.assertEqual(dt2.hour, 6)

    def test_clean_user_prompt(self):
        raw = (
            "<USER_REQUEST>\nFix bug\n</USER_REQUEST>\n"
            "<ADDITIONAL_METADATA>secret meta</ADDITIONAL_METADATA>"
        )
        self.assertEqual(clean_user_prompt(raw), "Fix bug")

    def test_extract_generic_body_and_exit_code(self):
        raw = "Created At: 2026-11-23T06:00:00Z\nCompleted At: 2026-11-23T06:00:05Z\nCommand exited with code 2\nboom"
        completed_dt, body = extract_generic_body(raw)
        self.assertIsNotNone(completed_dt)
        self.assertIn("Command exited with code 2", body)
        self.assertEqual(parse_step_exit_code(raw), 2)


if __name__ == "__main__":
    unittest.main()
