"""HTTP API router, hydrated HTML injector, and path-safe static asset server."""

import hashlib
import json
import os
import threading
import urllib.parse

from core.config import normalize_time_range

_STATIC_MIME_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


class WebAssetStore:
    """Thread-safe static asset reader with version hashing and traversal protection."""

    def __init__(self, web_dir):
        self.web_dir = os.path.abspath(web_dir)
        self._lock = threading.RLock()
        self._ui_sig = None
        self._ui_ver = "init"
        self._index_html = ""
        self._asset_cache = {}

    def _compute_ui_version(self):
        parts = []
        for root, _, files in os.walk(self.web_dir):
            for fn in sorted(files):
                ext = os.path.splitext(fn)[1].lower()
                if ext not in (".html", ".css", ".js", ".svg"):
                    continue
                fp = os.path.join(root, fn)
                rel = os.path.relpath(fp, self.web_dir).replace(os.sep, "/")
                try:
                    st = os.stat(fp)
                    parts.append((rel, st.st_mtime_ns, st.st_size))
                except OSError:
                    pass
        parts.sort()
        return tuple(parts)

    def get_index_html(self):
        """Return (index_html_with_ui_version, ui_version_hash)."""
        sig = self._compute_ui_version()
        with self._lock:
            if self._index_html and sig == self._ui_sig:
                return self._index_html, self._ui_ver

            index_path = os.path.join(self.web_dir, "index.html")
            if not os.path.exists(index_path):
                return "", "missing"

            h = hashlib.sha1()
            for rel, mtime_ns, size in sig:
                h.update(f"{rel}:{mtime_ns}:{size};".encode("utf-8"))
            ui_ver = h.hexdigest()[:16] if sig else "init"

            with open(index_path, "r", encoding="utf-8") as f:
                raw_html = f.read()

            self._index_html = raw_html.replace("__UI_VERSION__", ui_ver)
            self._ui_sig = sig
            self._ui_ver = ui_ver
            return self._index_html, self._ui_ver

    def get_static_asset(self, rel_path):
        """Safely resolve and cache a static file under web_dir, blocking path traversal."""
        raw = urllib.parse.unquote(rel_path or "")
        if not raw or "\x00" in raw or raw.startswith(("/", "\\")):
            return None

        parts = raw.replace("\\", "/").split("/")
        if any(p in ("", ".", "..") for p in parts):
            return None

        ext = os.path.splitext(parts[-1])[1].lower()
        mime = _STATIC_MIME_TYPES.get(ext)
        if not mime:
            return None

        real_root = os.path.realpath(self.web_dir)
        candidate = os.path.realpath(os.path.join(real_root, *parts))
        if not candidate.startswith(real_root + os.sep) or not os.path.isfile(candidate):
            return None

        try:
            st = os.stat(candidate)
            f_sig = (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

        with self._lock:
            cached = self._asset_cache.get(candidate)
            if cached and cached[0] == f_sig:
                return cached[1], cached[2]

        with open(candidate, "rb") as f:
            content = f.read()

        with self._lock:
            self._asset_cache[candidate] = (f_sig, mime, content)
        return mime, content


def _json_bytes(obj):
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def _safe_script_json(obj):
    """Serialize JSON safely for inline <script> injection without HTML tag breakouts."""
    return (
        json.dumps(obj, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def dispatch_get(path, qs, analytics_engine, multi_task_manager, asset_store, code_version="", reload_error=None):
    """Route GET requests for API endpoints, static assets, and hydrated HTML UI."""
    if path.startswith("/static/"):
        asset = asset_store.get_static_asset(path[len("/static/"):])
        if asset is None:
            return 404, "application/json; charset=utf-8", _json_bytes({"error": "Not found"})
        return 200, asset[0], asset[1]

    task_id = qs.get("task_id", [None])[0]
    time_range = normalize_time_range(qs.get("range", ["all"])[0])
    default_cid = task_id or os.environ.get("ANTIGRAVITY_CONVERSATION_ID") or None

    ui_html, ui_ver = asset_store.get_index_html()
    full_version = f"{code_version}|ui:{ui_ver}" if code_version else f"ui:{ui_ver}"

    if path == "/api/health":
        return 200, "application/json; charset=utf-8", _json_bytes({
            "ok": reload_error is None,
            "code_version": full_version,
            "core_version": code_version,
            "ui_version": ui_ver,
            "reload_error": reload_error,
            "pid": os.getpid(),
            "cached_transcripts": len(analytics_engine._file_step_cache),
            "cached_metas": len(analytics_engine._file_meta_cache),
            "cached_tails": len(multi_task_manager._tail_cache),
        })
    if path == "/api/session/context_timeline":
        cid = qs.get("cid", [default_cid])[0]
        return 200, "application/json; charset=utf-8", _json_bytes(analytics_engine.analyze_context_timeline(cid))
    if path == "/api/sessions":
        return 200, "application/json; charset=utf-8", _json_bytes(
            analytics_engine.collect_sessions_overview(default_cid, time_range=time_range)
        )
    if path == "/api/multi_task":
        return 200, "application/json; charset=utf-8", _json_bytes(
            multi_task_manager.collect_multi_task_report(task_id, time_range=time_range)
        )
    if path == "/api/task_steps":
        cid = qs.get("cid", [default_cid])[0]
        raw_step = qs.get("step", [None])[0]
        target_step = int(raw_step) if (raw_step is not None and str(raw_step).lstrip("-").isdigit()) else None
        raw_lim = qs.get("limit", [None])[0]
        lim = int(raw_lim) if (raw_lim is not None and str(raw_lim).isdigit()) else 30
        return 200, "application/json; charset=utf-8", _json_bytes(
            multi_task_manager.get_task_steps_window(cid, target_step=target_step, limit=lim)
        )
    if path == "/api/analytics":
        return 200, "application/json; charset=utf-8", _json_bytes(
            analytics_engine.collect_analytics(time_range=time_range)
        )

    known_ana = qs.get("known_ana", [None])[0]
    known_sess = qs.get("known_sess", [None])[0]
    mt_report = multi_task_manager.collect_multi_task_report(task_id, time_range=time_range)
    ana_report = analytics_engine.collect_analytics(time_range=time_range)
    sess_report = analytics_engine.collect_sessions_overview(default_cid, time_range=time_range)

    payload = {
        "code_version": full_version,
        "reload_error": reload_error,
        "time_range": time_range,
        "multi_task": mt_report,
        "analytics": None if (path == "/api/all" and known_ana and ana_report.get("sig") == known_ana) else ana_report,
        "sessions_overview": None if (path == "/api/all" and known_sess and sess_report.get("sig") == known_sess) else sess_report,
    }
    if path == "/api/all":
        return 200, "application/json; charset=utf-8", _json_bytes(payload)

    if not ui_html:
        return 500, "text/plain; charset=utf-8", b"web/index.html missing"

    hydrated_html = ui_html.replace("__INITIAL_DATA_PLACEHOLDER__", _safe_script_json(payload), 1)
    return 200, "text/html; charset=utf-8", hydrated_html.encode("utf-8")
