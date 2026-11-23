import glob
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

SIDE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sidecars", "task_monitor"))
if SIDE_DIR not in sys.path:
    sys.path.insert(0, SIDE_DIR)

from core.analytics import AntigravityAnalytics
from core.i18n import normalize_lang
from core.router import WebAssetStore, dispatch_get
from core.tasks import AntigravityMultiTaskManager

CJK_RE = re.compile(r"[\u4e00-\u9fff]")


class TestBilingualSupport(unittest.TestCase):
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
        self.cid_root = "aaaa1111-1111-4111-8111-111111111111"
        self.cid_legacy = "bbbb2222-2222-4222-8222-222222222222"
        self.cid_worker = "cccc3333-3333-4333-8333-333333333333"

        conn.execute(
            "INSERT INTO conversation_summaries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (self.cid_root, "Root Refactor", "CASCADE_RUN_STATUS_IDLE", 0, 5, now_iso, "file:///work/pulse-repo", "", ""),
        )
        conn.execute(
            "INSERT INTO conversation_summaries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (self.cid_legacy, "Legacy Session", "CASCADE_RUN_STATUS_IDLE", 0, 2, "0001-01-01T00:00:00Z", "file:///work/legacy-repo", "", ""),
        )
        conn.execute(
            "INSERT INTO conversation_summaries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (self.cid_worker, "Swarm Worker", "CASCADE_RUN_STATUS_RUNNING", 1, 2, now_iso, "file:///work/pulse-repo", self.cid_root, "analyst"),
        )
        conn.commit()
        conn.close()

        root_dir = os.path.join(self.tmpdir.name, "brain", self.cid_root, ".system_generated")
        os.makedirs(os.path.join(root_dir, "logs"), exist_ok=True)
        os.makedirs(os.path.join(root_dir, "swarm"), exist_ok=True)
        root_steps = [
            {
                "step_index": 0,
                "type": "USER_INPUT",
                "created_at": now_iso,
                "content": "<USER_REQUEST>Analyze bilingual support</USER_REQUEST>",
            },
            {
                "step_index": 1,
                "type": "PLANNER_RESPONSE",
                "created_at": now_iso,
                "model": "gemini-4-neon-high",
                "input_tokens": 12000,
                "cache_read_tokens": 30000,
                "output_tokens": 600,
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

        with open(os.path.join(root_dir, "swarm", "members.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "title": "Audit Swarm",
                    "members": {
                        "analyst": {
                            "conversation_id": self.cid_worker,
                            "role": "worker",
                            "desired_model": "gemini-4-argon-high",
                            "applied_model": "gemini-4-argon-high",
                            "phase": "WORKING",
                        }
                    },
                },
                f,
            )

        worker_logs = os.path.join(self.tmpdir.name, "brain", self.cid_worker, ".system_generated", "logs")
        os.makedirs(worker_logs, exist_ok=True)
        with open(os.path.join(worker_logs, "transcript.jsonl"), "w", encoding="utf-8") as f:
            f.write(json.dumps({"step_index": 0, "type": "USER_INPUT", "created_at": now_iso, "content": "Inspect"}))
            f.write("\n")
            f.write(
                json.dumps(
                    {
                        "step_index": 1,
                        "type": "PLANNER_RESPONSE",
                        "created_at": now_iso,
                        "input_tokens": 2000,
                        "cache_read_tokens": 8000,
                        "output_tokens": 200,
                        "tool_calls": [{"name": "swarm_wait", "args": {}}],
                    }
                )
            )
            f.write("\n")

        self.assets = WebAssetStore(os.path.join(SIDE_DIR, "web"))
        self.ana = AntigravityAnalytics()
        self.mgr = AntigravityMultiTaskManager(analytics_engine=self.ana)

    def tearDown(self):
        if self.prev_env is None:
            os.environ.pop("ANTIGRAVITY_DATA_DIRS", None)
        else:
            os.environ["ANTIGRAVITY_DATA_DIRS"] = self.prev_env
        self.tmpdir.cleanup()

    def test_normalize_lang_resolution(self):
        self.assertEqual(normalize_lang(None), "zh")
        self.assertEqual(normalize_lang(""), "zh")
        self.assertEqual(normalize_lang("en"), "en")
        self.assertEqual(normalize_lang("en-US"), "en")
        self.assertEqual(normalize_lang("zh-CN"), "zh")
        self.assertEqual(normalize_lang(None, "en-US,en;q=0.9"), "en")
        self.assertEqual(normalize_lang(None, "zh-CN,zh;q=0.9,en;q=0.8"), "zh")
        self.assertEqual(normalize_lang("zh", "en-US,en;q=0.9"), "zh")

    def test_all_api_endpoints_bilingual_and_zero_cjk_in_en(self):
        endpoints = [
            ("/api/health", {}),
            ("/api/all", {"range": ["today"]}),
            ("/api/analytics", {"range": ["today"]}),
            ("/api/sessions", {"range": ["all"]}),
            ("/api/multi_task", {"range": ["today"]}),
            ("/api/session/context_timeline", {"cid": [self.cid_root]}),
            ("/api/task_steps", {"cid": [self.cid_root], "limit": ["10"]}),
        ]
        for lang in ("zh", "en"):
            for path, qs_base in endpoints:
                qs = dict(qs_base)
                qs["lang"] = [lang]
                st, _, body = dispatch_get(path, qs, self.ana, self.mgr, self.assets, code_version="i18n-test")
                self.assertEqual(st, 200, f"{path} lang={lang} failed with {st}")
                text = body.decode("utf-8")
                payload = json.loads(text)
                self.assertEqual(payload.get("lang"), lang, f"{path} missing lang={lang}")
                if lang == "en":
                    cjk_matches = CJK_RE.findall(text)
                    self.assertEqual(
                        cjk_matches,
                        [],
                        f"CJK leakage in {path}?lang=en: {text[:400]}",
                    )

        # File-level transcript parse cache remains language-agnostic (one entry per file)
        self.assertGreaterEqual(len(self.ana._file_step_cache), 2)
        cached_count_before = len(self.ana._file_step_cache)
        dispatch_get("/api/all", {"range": ["today"], "lang": ["en"]}, self.ana, self.mgr, self.assets)
        self.assertEqual(len(self.ana._file_step_cache), cached_count_before)

    def test_accept_language_and_index_hydration(self):
        st_en, _, html_en_bytes = dispatch_get(
            "/",
            {},
            self.ana,
            self.mgr,
            self.assets,
            code_version="i18n-test",
            accept_language="en-US,en;q=0.9",
        )
        self.assertEqual(st_en, 200)
        html_en = html_en_bytes.decode("utf-8")
        self.assertIn("/static/js/i18n.js?v=", html_en)
        self.assertIn('"lang": "en"', html_en)

        st_js, ctype_js, js_bytes = dispatch_get(
            "/static/js/i18n.js", {}, self.ana, self.mgr, self.assets, code_version="i18n-test"
        )
        self.assertEqual(st_js, 200)
        self.assertIn("javascript", ctype_js)
        self.assertIn(b"function toggleLanguage", js_bytes)

    def test_frontend_i18n_dictionary_parity_and_shadow_safety(self):
        if not shutil.which("node"):
            self.skipTest("node binary not available")

        web_dir = os.path.join(SIDE_DIR, "web")
        extract_js = (
            "const fs = require('fs'); const vm = require('vm');"
            "const src = fs.readFileSync(process.argv[1], 'utf8');"
            "const ctx = { INITIAL_PAYLOAD: { lang: 'zh' } };"
            "vm.runInNewContext(src + '; globalThis.__I18N = I18N;', ctx);"
            "console.log(JSON.stringify(ctx.__I18N));"
        )
        res = subprocess.run(
            ["node", "-e", extract_js, os.path.join(web_dir, "js", "i18n.js")],
            capture_output=True,
            text=True,
            check=True,
        )
        i18n_data = json.loads(res.stdout)
        zh_keys = set(i18n_data["zh"].keys())
        en_keys = set(i18n_data["en"].keys())
        self.assertEqual(zh_keys, en_keys, "I18N.zh and I18N.en keys diverged")
        for k in zh_keys:
            self.assertTrue(isinstance(i18n_data["zh"][k], str) and i18n_data["zh"][k], f"Empty zh key: {k}")
            self.assertTrue(isinstance(i18n_data["en"][k], str) and i18n_data["en"][k], f"Empty en key: {k}")

        ref_keys = set()
        with open(os.path.join(web_dir, "index.html"), encoding="utf-8") as fh:
            html_src = fh.read()
        for m in re.finditer(r'data-i18n(?:-[a-z]+)?="([^"]+)"', html_src):
            ref_keys.add(m.group(1))

        for js_path in sorted(glob.glob(os.path.join(web_dir, "js", "*.js"))):
            if js_path.endswith("i18n.js"):
                continue
            with open(js_path, encoding="utf-8") as fh:
                src = fh.read()
            self.assertEqual(CJK_RE.findall(src), [], f"Remaining CJK chars in {os.path.basename(js_path)}")
            for m in re.finditer(r'(?:^|[^a-zA-Z0-9_.])(?:t|i18n)\(\s*[\'"]([^\'"]+)[\'"]', src):
                ref_keys.add(m.group(1))
            has_local_t = bool(re.search(r"\b(const|let|var)\s+t\b|\(\s*t\s*\)\s*=>|function\s+\w+\([^)]*\bt\b", src))
            if has_local_t:
                self.assertIsNone(
                    re.search(r"(?<![a-zA-Z0-9_.])t\(", src),
                    f"Shadowed t() call detected in {os.path.basename(js_path)}",
                )

        missing = sorted(ref_keys - zh_keys)
        self.assertEqual(missing, [], f"Undefined I18N keys referenced by UI: {missing}")


if __name__ == "__main__":
    unittest.main()
