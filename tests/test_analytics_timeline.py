import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone

SIDE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sidecars", "task_monitor"))
if SIDE_DIR not in sys.path:
    sys.path.insert(0, SIDE_DIR)

from core.analytics import AntigravityAnalytics
from core.tasks import AntigravityMultiTaskManager


class TestAnalyticsAndTimeline(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.prev_env = os.environ.get("ANTIGRAVITY_DATA_DIRS")
        os.environ["ANTIGRAVITY_DATA_DIRS"] = self.tmpdir.name

        db_path = os.path.join(self.tmpdir.name, "conversation_summaries.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            CREATE TABLE conversation_summaries (
                conversation_id TEXT PRIMARY KEY,
                title TEXT,
                status TEXT,
                not_fully_idle INTEGER,
                step_count INTEGER,
                last_modified_time TEXT,
                workspace_uris TEXT,
                parent_conversation_id TEXT,
                agent_name TEXT
            )
            """
        )
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.cid_root = "11111111-1111-4111-8111-111111111111"
        self.cid_legacy = "22222222-2222-4222-8222-222222222222"
        self.cid_worker = "33333333-3333-4333-8333-333333333333"

        conn.execute(
            "INSERT INTO conversation_summaries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (self.cid_root, "Root Refactor", "CASCADE_RUN_STATUS_IDLE", 0, 5, now_iso, "file:///work/pulse-repo", "", ""),
        )
        conn.execute(
            "INSERT INTO conversation_summaries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (self.cid_legacy, "Legacy Unbilled Session", "CASCADE_RUN_STATUS_IDLE", 0, 3, "0001-01-01T00:00:00Z", "file:///work/legacy-repo", "", ""),
        )
        conn.execute(
            "INSERT INTO conversation_summaries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (self.cid_worker, "Swarm Worker", "CASCADE_RUN_STATUS_IDLE", 0, 2, now_iso, "file:///work/pulse-repo", self.cid_root, "analyst"),
        )
        conn.commit()
        conn.close()

        # Root transcript with settings change + modern direct model + repeated reads + large tool output + compaction
        root_dir = os.path.join(self.tmpdir.name, "brain", self.cid_root, ".system_generated")
        os.makedirs(os.path.join(root_dir, "logs"), exist_ok=True)
        os.makedirs(os.path.join(root_dir, "swarm"), exist_ok=True)

        root_steps = [
            {
                "step_index": 0,
                "type": "USER_INPUT",
                "created_at": now_iso,
                "content": (
                    "<USER_REQUEST>Analyze system</USER_REQUEST>"
                    "<USER_SETTINGS_CHANGE>changed setting `Model Selection` from Gemini 4 Neon (High) to Claude Sonnet 4.6 (Thinking). No need</USER_SETTINGS_CHANGE>"
                ),
            },
            {
                "step_index": 1,
                "type": "PLANNER_RESPONSE",
                "created_at": now_iso,
                "input_tokens": 10000,
                "cache_read_tokens": 40000,
                "output_tokens": 500,
                "thinking": "checking",
                "tool_calls": [
                    {"name": "read_file", "args": {"Path": "/repo/app.py"}},
                    {"name": "read_file", "args": {"Path": "/repo/app.py"}},
                    {"name": "read_file", "args": {"Path": "/repo/app.py"}},
                ],
            },
            {
                "step_index": 2,
                "type": "GENERIC",
                "created_at": now_iso,
                "content": "Completed At: " + now_iso + "\n" + ("x" * 13000),
            },
            {
                "step_index": 3,
                "type": "USER_INPUT",
                "created_at": now_iso,
                "content": "<CONTEXT_SUMMARY>compressed</CONTEXT_SUMMARY> Continue",
            },
            {
                "step_index": 4,
                "type": "PLANNER_RESPONSE",
                "created_at": now_iso,
                "model": "gemini-4-neon-xhigh",
                "input_tokens": 5000,
                "cache_read_tokens": 10000,
                "output_tokens": 400,
                "content": "Done",
            },
        ]
        with open(os.path.join(root_dir, "logs", "transcript.jsonl"), "w", encoding="utf-8") as f:
            for st in root_steps:
                f.write(json.dumps(st) + "\n")

        swarm_members = {
            "title": "Audit Swarm",
            "members": {
                "analyst": {
                    "conversation_id": self.cid_worker,
                    "role": "worker",
                    "desired_model": "gemini-4-argon-high",
                    "applied_model": "gemini-4-argon-high",
                    "phase": "SLEEPING",
                }
            },
        }
        with open(os.path.join(root_dir, "swarm", "members.json"), "w", encoding="utf-8") as f:
            json.dump(swarm_members, f)

        # Worker transcript without explicit model (should resolve via Swarm Tier 2)
        worker_logs = os.path.join(self.tmpdir.name, "brain", self.cid_worker, ".system_generated", "logs")
        os.makedirs(worker_logs, exist_ok=True)
        with open(os.path.join(worker_logs, "transcript.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"step_index": 0, "type": "USER_INPUT", "created_at": now_iso, "content": "Inspect"}))
            f.write("\n")
            f.write(
                json.dumps({
                    "step_index": 1,
                    "type": "PLANNER_RESPONSE",
                    "created_at": now_iso,
                    "input_tokens": 2000,
                    "cache_read_tokens": 8000,
                    "output_tokens": 200,
                    "content": "Report ready",
                })
                + "\n"
            )

        # Legacy unbilled session with 0001-01-01 DB timestamp & legacy VIEW_FILE step type
        legacy_logs = os.path.join(self.tmpdir.name, "brain", self.cid_legacy, ".system_generated", "logs")
        os.makedirs(legacy_logs, exist_ok=True)
        with open(os.path.join(legacy_logs, "transcript.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"step_index": 0, "type": "USER_INPUT", "created_at": now_iso, "content": "Old task"}) + "\n")
            f.write(
                json.dumps({
                    "step_index": 1,
                    "type": "PLANNER_RESPONSE",
                    "created_at": now_iso,
                    "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "/repo/old.py"}}],
                })
                + "\n"
            )
            f.write(json.dumps({"step_index": 2, "type": "VIEW_FILE", "created_at": now_iso, "content": "file body " * 200}) + "\n")

    def tearDown(self):
        if self.prev_env is None:
            os.environ.pop("ANTIGRAVITY_DATA_DIRS", None)
        else:
            os.environ["ANTIGRAVITY_DATA_DIRS"] = self.prev_env
        self.tmpdir.cleanup()

    def test_analytics_model_usage_and_legacy_fallback(self):
        ana = AntigravityAnalytics()
        rep = ana.collect_analytics(time_range="today")
        mu = rep["model_usage"]
        names = {it["name"]: it for it in mu["items"]}

        # Tier 3 stripped effort -> Claude Sonnet 4.6
        self.assertIn("Claude Sonnet 4.6", names)
        # Tier 1 stripped effort -> Gemini 4 Neon
        self.assertIn("Gemini 4 Neon", names)
        # Tier 2 Swarm members.json -> Gemini 4 Argon
        self.assertIn("Gemini 4 Argon", names)
        # Legacy step fallback -> 未记录 (历史日志)
        self.assertIn("未记录 (历史日志)", names)
        self.assertEqual(mu["total_calls"], 4)

    def test_sessions_overview_and_0001_fallback(self):
        ana = AntigravityAnalytics()
        sess = ana.collect_sessions_overview(current_cid=self.cid_root, time_range="7d")
        ids = {s["id"]: s for s in sess["sessions"]}
        # Legacy DB timestamp was 0001-01-01, but resolved via transcript created_at into 7d window!
        self.assertIn(self.cid_legacy, ids)
        self.assertIn(self.cid_root, ids)
        self.assertTrue(ids[self.cid_root]["current"])
        self.assertFalse(ids[self.cid_legacy]["current"])
        self.assertEqual(ids[self.cid_root]["primary_model"], "Claude Sonnet 4.6")

    def test_context_timeline_diagnostics(self):
        ana = AntigravityAnalytics()
        tl = ana.analyze_context_timeline(self.cid_root)
        self.assertEqual(tl["turns_count"], 2)
        self.assertTrue(tl["large_tools"])
        self.assertTrue(tl["repeated_reads"])
        self.assertTrue(tl["compaction_events"])
        # Legacy unbilled session should compute non-2500 real text delta
        tl_leg = ana.analyze_context_timeline(self.cid_legacy)
        self.assertEqual(tl_leg["turns_count"], 1)
        self.assertNotEqual(tl_leg["turns"][0]["delta"], 2500)

    def test_multi_task_manager_swarm_topology(self):
        ana = AntigravityAnalytics()
        mgr = AntigravityMultiTaskManager(analytics_engine=ana)
        mt = mgr.collect_multi_task_report(focused_cid=self.cid_root, time_range="7d")
        tasks = {t["conversation_id"]: t for t in mt["all_tasks"]}
        self.assertIn(self.cid_root, tasks)
        self.assertIn(self.cid_legacy, tasks)
        self.assertEqual(tasks[self.cid_root]["subagents_count"], 1)
        self.assertTrue(tasks[self.cid_root]["swarm"]["is_swarm"])


if __name__ == "__main__":
    unittest.main()
