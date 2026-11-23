import json
import os
import sys
import tempfile
import unittest

SIDE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "sidecars", "task_monitor"))
if SIDE_DIR not in sys.path:
    sys.path.insert(0, SIDE_DIR)

import server
from core.analytics import AntigravityAnalytics
from core.router import WebAssetStore, _safe_script_json, dispatch_get
from core.tasks import AntigravityMultiTaskManager


class TestServerAndRouter(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.prev_env = os.environ.get("ANTIGRAVITY_DATA_DIRS")
        os.environ["ANTIGRAVITY_DATA_DIRS"] = self.tmpdir.name
        self.web_dir = os.path.join(SIDE_DIR, "web")
        self.assets = WebAssetStore(self.web_dir)
        self.ana = AntigravityAnalytics()
        self.mgr = AntigravityMultiTaskManager(analytics_engine=self.ana)

    def tearDown(self):
        if self.prev_env is None:
            os.environ.pop("ANTIGRAVITY_DATA_DIRS", None)
        else:
            os.environ["ANTIGRAVITY_DATA_DIRS"] = self.prev_env
        self.tmpdir.cleanup()

    def test_cors_allows_loopback_only(self):
        class DummyHandler:
            def __init__(self, origin=None):
                self.headers = {"Origin": origin} if origin is not None else {}

        self.assertEqual(
            server.SidecarHandler._allowed_origin(DummyHandler("http://127.0.0.1:55608")),
            "http://127.0.0.1:55608",
        )
        self.assertEqual(
            server.SidecarHandler._allowed_origin(DummyHandler("https://localhost:8443")),
            "https://localhost:8443",
        )
        self.assertEqual(
            server.SidecarHandler._allowed_origin(DummyHandler("https://evil.example.com")),
            "http://127.0.0.1",
        )
        self.assertEqual(
            server.SidecarHandler._allowed_origin(DummyHandler(None)),
            "http://127.0.0.1",
        )

    def test_static_asset_serving_and_traversal_blocking(self):
        status, ctype, css_bytes = dispatch_get(
            "/static/styles.css", {}, self.ana, self.mgr, self.assets, code_version="test"
        )
        self.assertEqual(status, 200)
        self.assertIn("text/css", ctype)
        self.assertIn(b".model-table", css_bytes)

        for bad_path in (
            "/static/../server.py",
            "/static/%2e%2e/server.py",
            "/static/js/../../monitor_core.py",
            "/static//etc/passwd",
            "/static/index.html",
        ):
            st, _, _ = dispatch_get(bad_path, {}, self.ana, self.mgr, self.assets)
            self.assertEqual(st, 404, f"Expected 404 for {bad_path}, got {st}")

    def test_index_hydration_and_script_json_escaping(self):
        escaped = _safe_script_json({"msg": "</script><img onerror=alert(1)>&"})
        self.assertNotIn("</script>", escaped)
        self.assertIn("\\u003c/script\\u003e", escaped)

        st, ctype, html_bytes = dispatch_get("/", {}, self.ana, self.mgr, self.assets, code_version="abc")
        self.assertEqual(st, 200)
        self.assertIn("text/html", ctype)
        html_str = html_bytes.decode("utf-8")
        self.assertIn("/static/styles.css?v=", html_str)
        self.assertIn("/static/js/app.js?v=", html_str)
        self.assertNotIn("__INITIAL_DATA_PLACEHOLDER__", html_str)
        self.assertNotIn("__UI_VERSION__", html_str)

    def test_health_endpoint(self):
        st, _, body = dispatch_get("/api/health", {}, self.ana, self.mgr, self.assets, code_version="abc")
        self.assertEqual(st, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertTrue(data["ok"])
        self.assertEqual(data["core_version"], "abc")


if __name__ == "__main__":
    unittest.main()
