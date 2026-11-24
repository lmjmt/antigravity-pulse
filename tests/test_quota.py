import json
import os
import re
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

SIDE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sidecars", "task_monitor"))
if SIDE_DIR not in sys.path:
    sys.path.insert(0, SIDE_DIR)

from core import quota
from core.analytics import AntigravityAnalytics
from core.router import WebAssetStore, dispatch_get
from core.tasks import AntigravityMultiTaskManager

CJK_RE = re.compile(r"[\u4e00-\u9fff]")


class _MockLSHandler(BaseHTTPRequestHandler):
    requests_seen = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or "0")
        raw_body = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
        self.__class__.requests_seen.append({
            "path": self.path,
            "csrf": self.headers.get("x-codeium-csrf-token"),
            "proto": self.headers.get("Connect-Protocol-Version"),
            "body": json.loads(raw_body),
        })

        if self.headers.get("x-codeium-csrf-token") != "test-csrf-secret":
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b'{"error":"forbidden"}')
            return

        future_weekly = (datetime.now(timezone.utc) + timedelta(days=6, hours=18)).strftime("%Y-%m-%dT%H:%M:%SZ")
        future_5h = (datetime.now(timezone.utc) + timedelta(hours=4, minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

        if self.path.endswith("/RetrieveUserQuotaSummary"):
            payload = {
                "response": {
                    "groups": [
                        {
                            "displayName": "Gemini Models",
                            "description": "Shared Gemini pool",
                            "buckets": [
                                {
                                    "bucketId": "gemini_weekly",
                                    "window": "weekly",
                                    "displayName": "Weekly limit",
                                    "remainingFraction": 0.66,
                                    "resetTime": future_weekly,
                                },
                                {
                                    "bucketId": "gemini_5h",
                                    "window": "5h",
                                    "displayName": "5h limit",
                                    "remainingFraction": 0.84,
                                    "resetTime": future_5h,
                                },
                            ],
                        },
                        {
                            "displayName": "Claude and GPT models",
                            "buckets": [
                                {
                                    "bucketId": "partner_weekly",
                                    "window": "weekly",
                                    "displayName": "Weekly limit",
                                    "remainingFraction": 0.12,
                                    "resetTime": future_weekly,
                                },
                            ],
                        },
                    ]
                }
            }
        elif self.path.endswith("/GetCascadeModelConfigData"):
            payload = {
                "clientModelConfigs": [
                    {
                        "modelId": "gemini-4-hydrogen-high",
                        "label": "Gemini 4 Hydrogen (High)",
                        "isRecommended": True,
                        "quotaInfo": {
                            "remainingFraction": 0.84,
                            "resetTime": future_5h,
                        },
                    },
                    {
                        "modelId": "gemini-4-argon-high",
                        "label": "Gemini 4 Argon (High)",
                        "quotaInfo": {
                            "remainingFraction": 0.35,
                            "resetTime": future_weekly,
                        },
                    },
                ]
            }
        elif self.path.endswith("/GetUserStatus"):
            payload = {
                "userTier": "TEAMS_TIER_PRO",
                "planStatus": {"planInfo": {"planName": "Google AI Pro"}},
                "userStatus": {"email": "private-user@example.com"},
            }
        else:
            self.send_response(404)
            self.end_headers()
            return

        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):
        return


class TestQuotaModule(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self._env_backup = {
            k: os.environ.get(k)
            for k in ("ANTIGRAVITY_DATA_DIRS", "ANTIGRAVITY_LS_ADDRESS", "ANTIGRAVITY_CSRF_TOKEN", "ANTIGRAVITY_QUOTA_TTL")
        }
        os.environ["ANTIGRAVITY_DATA_DIRS"] = self.tmpdir.name
        os.environ.pop("ANTIGRAVITY_LS_ADDRESS", None)
        os.environ.pop("ANTIGRAVITY_CSRF_TOKEN", None)
        os.environ.pop("ANTIGRAVITY_QUOTA_TTL", None)
        with quota.QUOTA_CACHE_LOCK:
            quota.QUOTA_CACHE["sig"] = None
            quota.QUOTA_CACHE["ts"] = 0.0
            quota.QUOTA_CACHE["raw"] = None
        self.assets = WebAssetStore(os.path.join(SIDE_DIR, "web"))
        self.ana = AntigravityAnalytics()
        self.mgr = AntigravityMultiTaskManager(analytics_engine=self.ana)

    def tearDown(self):
        for k, v in self._env_backup.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmpdir.cleanup()

    def test_parse_ls_endpoint_loopback_only(self):
        os.environ["ANTIGRAVITY_LS_ADDRESS"] = "https://127.0.0.1:43123"
        os.environ["ANTIGRAVITY_CSRF_TOKEN"] = "abc"
        ep = quota.parse_ls_endpoint()
        self.assertIsNotNone(ep)
        self.assertEqual(ep["host"], "127.0.0.1")
        self.assertEqual(ep["port"], 43123)
        self.assertEqual(ep["schemes"], ("https", "http"))

        os.environ["ANTIGRAVITY_LS_ADDRESS"] = ":43124"
        ep2 = quota.parse_ls_endpoint()
        self.assertIsNotNone(ep2)
        self.assertEqual(ep2["port"], 43124)

        for bad in ("https://evil.example.com:443", "http://192.168.1.10:8080", "127.0.0.1:0", "invalid"):
            os.environ["ANTIGRAVITY_LS_ADDRESS"] = bad
            self.assertIsNone(quota.parse_ls_endpoint(), f"Should reject {bad}")

    def test_unconfigured_fallback_and_zero_cjk_in_en(self):
        res_zh = quota.collect_quota(lang="zh")
        self.assertFalse(res_zh["available"])
        self.assertEqual(res_zh["status"], "unconfigured")
        self.assertEqual(res_zh["groups"], [])

        res_en = quota.collect_quota(lang="en")
        self.assertFalse(res_en["available"])
        self.assertEqual(res_en["status"], "unconfigured")
        self.assertEqual(CJK_RE.findall(json.dumps(res_en, ensure_ascii=False)), [])

    def test_live_rpc_collection_cache_and_router(self):
        _MockLSHandler.requests_seen = []
        srv = HTTPServer(("127.0.0.1", 0), _MockLSHandler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            os.environ["ANTIGRAVITY_LS_ADDRESS"] = f"http://127.0.0.1:{port}"
            os.environ["ANTIGRAVITY_CSRF_TOKEN"] = "test-csrf-secret"

            q_zh = quota.collect_quota(lang="zh", force=False)
            self.assertTrue(q_zh["available"])
            self.assertEqual(q_zh["status"], "ok")
            self.assertEqual(q_zh["plan_tier"], "Google AI Pro")
            self.assertNotIn("private-user@example.com", json.dumps(q_zh))
            self.assertEqual(len(q_zh["groups"]), 2)
            self.assertEqual(q_zh["groups"][0]["buckets"][0]["remaining_pct"], 66.0)
            self.assertEqual(q_zh["groups"][0]["buckets"][0]["level"], "ok")
            self.assertEqual(q_zh["groups"][1]["buckets"][0]["level"], "crit")
            self.assertEqual(len(q_zh["models"]), 2)
            self.assertFalse(q_zh["cached"])

            req_count_after_first = len(_MockLSHandler.requests_seen)
            self.assertEqual(req_count_after_first, 3)
            self.assertEqual(_MockLSHandler.requests_seen[0]["proto"], "1")

            # Cached hit in English without re-querying LS and without CJK characters
            q_en = quota.collect_quota(lang="en", force=False)
            self.assertTrue(q_en["cached"])
            self.assertEqual(len(_MockLSHandler.requests_seen), req_count_after_first)
            self.assertEqual(CJK_RE.findall(json.dumps(q_en, ensure_ascii=False)), [])

            # Router /api/quota?force=1 bypasses TTL cache
            st, _, body = dispatch_get("/api/quota", {"lang": ["en"], "force": ["1"]}, self.ana, self.mgr, self.assets)
            self.assertEqual(st, 200)
            api_q = json.loads(body.decode("utf-8"))
            self.assertFalse(api_q["cached"])
            self.assertGreater(len(_MockLSHandler.requests_seen), req_count_after_first)

            # Router /api/all respects known_quota
            st2, _, body2 = dispatch_get(
                "/api/all",
                {"lang": ["en"], "known_quota": [api_q["sig"]]},
                self.ana,
                self.mgr,
                self.assets,
            )
            self.assertEqual(st2, 200)
            all_payload = json.loads(body2.decode("utf-8"))
            self.assertIsNone(all_payload["quota"])
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
