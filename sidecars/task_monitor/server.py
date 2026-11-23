#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Antigravity Pulse Sidecar Host (Hot-Reload Wrapper)
---------------------------------------------------
Keeps the IDE-assigned port, PID, and auth token stable across code updates.
UI and analytics live in monitor_core.py + core/*.py and web/*, and are
atomically hot-reloaded on file modification so Cmd+R renders latest changes
with zero process restart.
"""

import glob
import hashlib
import importlib.util
import json
import os
import signal
import socket
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.dont_write_bytecode = True

_HERE = os.path.dirname(os.path.abspath(__file__))
CORE_PATH = os.path.join(_HERE, "monitor_core.py")
CORE_PKG_DIR = os.path.join(_HERE, "core")
DEFAULT_DATA_DIRS = (
    os.path.expanduser("~/.gemini/antigravity"),
    os.path.expanduser("~/.gemini/antigravity-cli"),
    os.path.expanduser("~/.gemini/antigravity-ide"),
)


def _get_data_dirs():
    override = os.environ.get("ANTIGRAVITY_DATA_DIRS", "").strip()
    if override:
        return [os.path.expanduser(p.strip()) for p in override.split(os.pathsep) if p.strip()]
    return list(DEFAULT_DATA_DIRS)


def _detect_plugin_dir_name():
    # server.py lives under <plugin_dir>/sidecars/<sidecar_name>/server.py
    plugin_root = os.path.dirname(os.path.dirname(_HERE))
    name = os.path.basename(plugin_root)
    return name or "antigravity-pulse"


class _HotCoreLoader:
    """Thread-safe atomic loader watching monitor_core.py and core/*.py."""

    def __init__(self, core_path, core_pkg_dir):
        self.core_path = core_path
        self.core_pkg_dir = core_pkg_dir
        self._lock = threading.RLock()
        self._sig = None
        self._version = "init"
        self._mod = None
        self._last_error = None

    def _compute_sig(self):
        watched = [self.core_path]
        if os.path.isdir(self.core_pkg_dir):
            watched.extend(sorted(glob.glob(os.path.join(self.core_pkg_dir, "*.py"))))
        entries = []
        for fp in watched:
            st = os.stat(fp)
            entries.append((fp, st.st_mtime_ns, st.st_size))
        return tuple(entries)

    @staticmethod
    def _version_from_sig(sig):
        h = hashlib.sha1()
        for fp, mtime_ns, size in sig:
            h.update(f"{os.path.basename(fp)}:{mtime_ns}:{size};".encode("utf-8"))
        return h.hexdigest()[:16]

    def get_core(self):
        with self._lock:
            try:
                sig = self._compute_sig()
            except OSError as e:
                self._last_error = str(e)
                return self._mod, self._version, self._last_error

            if self._mod is not None and sig == self._sig:
                return self._mod, self._version, self._last_error

            prev_mod = self._mod
            try:
                spec = importlib.util.spec_from_file_location("monitor_core", self.core_path)
                new_mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(new_mod)
                if prev_mod is not None and hasattr(new_mod, "migrate_caches_from"):
                    new_mod.migrate_caches_from(prev_mod)
                sys.modules["monitor_core"] = new_mod
                self._mod = new_mod
                self._sig = sig
                self._version = self._version_from_sig(sig)
                self._last_error = None
            except Exception as e:
                self._last_error = str(e)
                sys.stderr.write(f"[antigravity-pulse] hot-reload error (keeping previous version): {e}\n")

            return self._mod, self._version, self._last_error


CORE_LOADER = _HotCoreLoader(CORE_PATH, CORE_PKG_DIR)


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class SidecarHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        core, code_ver, reload_err = CORE_LOADER.get_core()

        if core is None:
            body = json.dumps({"error": reload_err or "monitor_core.py unavailable"}).encode("utf-8")
            self._write_response(500, "application/json; charset=utf-8", body)
            return

        try:
            status, content_type, body = core.dispatch_get(
                parsed.path, qs, code_version=code_ver, reload_error=reload_err
            )
            self._write_response(status, content_type, body)
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode("utf-8")
            self._write_response(500, "application/json; charset=utf-8", body)

    def _allowed_origin(self):
        origin = (self.headers.get("Origin") or "").strip() if hasattr(self, "headers") else ""
        if origin:
            try:
                p = urllib.parse.urlparse(origin)
                if p.scheme in ("http", "https") and p.hostname in ("127.0.0.1", "localhost"):
                    return origin
            except Exception:
                pass
        return "http://127.0.0.1"

    def _write_response(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Access-Control-Allow-Origin", self._allowed_origin())
        self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def write_server_info(port):
    info = {
        "host": "127.0.0.1",
        "port": port,
        "token": os.environ.get("ANTIGRAVITY_SIDECAR_UI_TOKEN") or None,
        "pid": os.getpid(),
    }
    plugin_name = _detect_plugin_dir_name()
    for d in _get_data_dirs():
        sidecar_data_dir = os.path.join(d, "sidecar_data", plugin_name, "task_monitor", "data")
        try:
            os.makedirs(sidecar_data_dir, exist_ok=True)
            with open(os.path.join(sidecar_data_dir, "server_info.json"), "w", encoding="utf-8") as f:
                json.dump(info, f, indent=2)
        except Exception:
            pass


def find_free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main():
    CORE_LOADER.get_core()
    raw_port = os.environ.get("ANTIGRAVITY_SIDECAR_WEB_PORT")
    port = int(raw_port) if raw_port and raw_port.isdigit() and int(raw_port) > 0 else 8999

    try:
        server = ReusableThreadingHTTPServer(("127.0.0.1", port), SidecarHandler)
    except OSError:
        port = find_free_port()
        server = ReusableThreadingHTTPServer(("127.0.0.1", port), SidecarHandler)

    write_server_info(port)
    sys.stderr.write(f"Antigravity Pulse Monitor (hot-reload) running on http://127.0.0.1:{port}\n")

    def handle_exit(signum, frame):
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)
    server.serve_forever()


if __name__ == "__main__":
    main()
