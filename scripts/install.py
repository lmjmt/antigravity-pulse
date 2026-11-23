#!/usr/bin/env python3
"""Cross-platform installer, updater, doctor, and uninstaller for Antigravity Pulse.

Supports macOS, Linux, and Windows using only Python 3.9+ standard library.
"""

import argparse
import hashlib
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_REPO = "lmjmt/antigravity-pulse"
PLUGIN_DIR_NAME = "antigravity-pulse"
INSTALL_SUBDIRS = ("assets", "hooks", "rules", "skills", "sidecars")
INSTALL_FILES = ("plugin.json", "hooks.json", "README.md", "README.zh-CN.md")
EXCLUDE_NAMES = {"__pycache__", ".DS_Store"}


def _default_plugins_base():
    env_dir = os.environ.get("ANTIGRAVITY_PLUGINS_DIR", "").strip()
    if env_dir:
        return Path(os.path.expanduser(env_dir)).resolve()
    return (Path.home() / ".gemini" / "config" / "plugins").resolve()


def _detect_local_repo():
    here = Path(__file__).resolve()
    candidate = here.parent.parent
    if (candidate / "plugin.json").is_file() and (candidate / "sidecars" / "task_monitor" / "server.py").is_file():
        return candidate
    return None


def _discover_data_dirs():
    override = os.environ.get("ANTIGRAVITY_DATA_DIRS", "").strip()
    if override:
        raw = [os.path.expanduser(p.strip()) for p in override.split(os.pathsep) if p.strip()]
    else:
        raw = [
            os.path.expanduser("~/.gemini/antigravity"),
            os.path.expanduser("~/.gemini/antigravity-cli"),
            os.path.expanduser("~/.gemini/antigravity-ide"),
        ]
    return [Path(p) for p in raw]


def run_doctor(plugins_base, verbose=True):
    """Inspect runtime prerequisites and potential plugin conflicts."""
    issues = []
    warnings = []

    py_ver = sys.version_info
    py_ok = (py_ver.major, py_ver.minor) >= (3, 9)
    if not py_ok:
        issues.append(f"Python 3.9+ is required (found {py_ver.major}.{py_ver.minor}.{py_ver.micro})")

    data_dirs = _discover_data_dirs()
    existing_data = [d for d in data_dirs if d.is_dir()]
    if not existing_data:
        warnings.append(
            "No Antigravity data directory found yet (~/.gemini/antigravity*). "
            "Launch Antigravity once or set ANTIGRAVITY_DATA_DIRS."
        )

    legacy_plugin = plugins_base / "task-monitor"
    pulse_plugin = plugins_base / PLUGIN_DIR_NAME
    if legacy_plugin.is_dir():
        warnings.append(
            f"Legacy plugin directory detected at {legacy_plugin}. "
            "Running both 'task-monitor' and 'antigravity-pulse' simultaneously may launch two sidecars. "
            "Tip: disable one in Antigravity Customizations, or use '--sync-sidecar task-monitor'."
        )

    if verbose:
        print("=== Antigravity Pulse Preflight Doctor ===")
        print(f"[{'OK' if py_ok else 'FAIL'}] Python version: {py_ver.major}.{py_ver.minor}.{py_ver.micro}")
        print(f"[INFO] Plugins directory: {plugins_base}")
        print(f"[{'OK' if pulse_plugin.is_dir() else 'INFO'}] Installed ({PLUGIN_DIR_NAME}): {'yes' if pulse_plugin.is_dir() else 'no'}")
        print(f"[{'OK' if existing_data else 'WARN'}] Antigravity data dirs found: {len(existing_data)}")
        for d in existing_data:
            print(f"       - {d}")
        for w in warnings:
            print(f"[WARN] {w}")
        for err in issues:
            print(f"[FAIL] {err}")

    return {"ok": len(issues) == 0, "issues": issues, "warnings": warnings}


def _copy_tree_clean(src, dst, dry_run=False):
    src_path = Path(src)
    dst_path = Path(dst)
    if not src_path.exists():
        return
    if dry_run:
        print(f"  [dry-run] sync {src_path} -> {dst_path}")
        return
    if dst_path.exists():
        shutil.rmtree(dst_path)

    def _ignore(_dir, names):
        ignored = []
        for n in names:
            if n in EXCLUDE_NAMES or n.endswith(".pyc"):
                ignored.append(n)
        return ignored

    shutil.copytree(src_path, dst_path, ignore=_ignore)


def _copy_file_clean(src, dst, dry_run=False):
    src_path = Path(src)
    dst_path = Path(dst)
    if not src_path.is_file():
        return
    if dry_run:
        print(f"  [dry-run] copy {src_path} -> {dst_path}")
        return
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_path, dst_path)


def _safe_extract_tar(archive_path, extract_dir):
    extract_root = Path(extract_dir).resolve()
    with tarfile.open(archive_path, "r:*") as tf:
        for member in tf.getmembers():
            member_path = (extract_root / member.name).resolve()
            try:
                member_path.relative_to(extract_root)
            except ValueError as exc:
                raise RuntimeError(f"Blocked unsafe archive path: {member.name}") from exc
            if member.issym() or member.islnk():
                raise RuntimeError(f"Blocked symlink/hardlink in archive: {member.name}")
        tf.extractall(extract_root)


def _locate_repo_in_dir(base_dir):
    base = Path(base_dir)
    if (base / "plugin.json").is_file():
        return base
    for child in sorted(base.iterdir()):
        if child.is_dir() and (child / "plugin.json").is_file():
            return child
    raise RuntimeError("Downloaded archive does not contain a valid plugin.json root.")


def _resolve_archive_url(repo, version, archive_url):
    if archive_url:
        return archive_url
    ref = (version or "main").strip()
    if ref.startswith("v"):
        return f"https://github.com/{repo}/archive/refs/tags/{ref}.tar.gz"
    return f"https://github.com/{repo}/archive/refs/heads/{ref}.tar.gz"


def _download_and_extract(url, dest_dir, expected_sha256=""):
    archive_file = Path(dest_dir) / "source.tar.gz"
    headers = {"User-Agent": "antigravity-pulse-installer/1.2"}
    gh_token = os.environ.get("GITHUB_TOKEN", "").strip()
    gl_token = os.environ.get("GITLAB_TOKEN", "").strip()
    if gh_token and "github.com" in url:
        headers["Authorization"] = f"Bearer {gh_token}"
    elif gl_token:
        headers["PRIVATE-TOKEN"] = gl_token

    if url.startswith("file://") or Path(url).is_file():
        local_src = url[7:] if url.startswith("file://") else url
        shutil.copy2(local_src, archive_file)
    else:
        print(f"Downloading {url} ...")
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp, open(archive_file, "wb") as out:
                shutil.copyfileobj(resp, out)
        except urllib.error.HTTPError as exc:
            hint = ""
            if exc.code in (401, 403, 404):
                hint = " (If this repository is private, export GITHUB_TOKEN or GITLAB_TOKEN and retry.)"
            raise RuntimeError(f"Download failed with HTTP {exc.code}: {url}{hint}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Network error downloading {url}: {exc.reason}") from exc

    if expected_sha256:
        digest = hashlib.sha256(archive_file.read_bytes()).hexdigest().lower()
        if digest != expected_sha256.strip().lower():
            raise RuntimeError(f"SHA256 mismatch: expected {expected_sha256}, got {digest}")

    extract_root = Path(dest_dir) / "extracted"
    extract_root.mkdir(parents=True, exist_ok=True)
    _safe_extract_tar(archive_file, extract_root)
    return _locate_repo_in_dir(extract_root)


def install_plugin(source_root, plugins_base, dry_run=False):
    target_dir = plugins_base / PLUGIN_DIR_NAME
    print(f"Installing {PLUGIN_DIR_NAME} -> {target_dir}")
    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)
    for sub in INSTALL_SUBDIRS:
        _copy_tree_clean(Path(source_root) / sub, target_dir / sub, dry_run=dry_run)
    for fname in INSTALL_FILES:
        _copy_file_clean(Path(source_root) / fname, target_dir / fname, dry_run=dry_run)

    if not dry_run:
        print("")
        print("Installed successfully / 安装完成!")
        print(f"  Path / 路径 : {target_dir}")
        print("  Next / 后续 :")
        print("    1. Enable 'Antigravity Pulse' in Antigravity Customizations (no restart needed for updates).")
        print("       在 Antigravity Customizations 面板启用 Antigravity Pulse（升级覆盖后按 Cmd+R 即可热更新）。")
        print("    2. Open dashboard in chat: [⚡ Antigravity Pulse](sidecar://antigravity-pulse/task_monitor/)")


def sync_sidecar(source_root, plugins_base, target_plugin_name, dry_run=False):
    target_plugin = plugins_base / target_plugin_name
    if not target_plugin.is_dir():
        raise RuntimeError(f"Target plugin directory not found: {target_plugin}")

    src_sidecar = Path(source_root) / "sidecars" / "task_monitor"
    dst_sidecar = target_plugin / "sidecars" / "task_monitor"
    print(f"Syncing modular sidecar into {dst_sidecar} ...")
    _copy_tree_clean(src_sidecar / "core", dst_sidecar / "core", dry_run=dry_run)
    _copy_tree_clean(src_sidecar / "web", dst_sidecar / "web", dry_run=dry_run)
    for fname in ("monitor_core.py", "server.py", "sidecar.json"):
        _copy_file_clean(src_sidecar / fname, dst_sidecar / fname, dry_run=dry_run)

    if not dry_run:
        print("Done! Sidecar code synced (press Cmd+R in side pane to hot-reload ui/backend).")


def uninstall_plugin(plugins_base, dry_run=False):
    target_dir = plugins_base / PLUGIN_DIR_NAME
    if not target_dir.exists():
        print(f"Nothing to uninstall: {target_dir} does not exist.")
        return
    if dry_run:
        print(f"[dry-run] remove {target_dir}")
        return
    shutil.rmtree(target_dir)
    print(f"Uninstalled {PLUGIN_DIR_NAME} from {target_dir}.")
    print("Note: disable/refresh in Antigravity Customizations if the side pane is still open.")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="install.py",
        description="Install, update, sync, diagnose, or uninstall Antigravity Pulse.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--doctor", action="store_true", help="Run environment & conflict preflight checks only")
    mode.add_argument("--uninstall", action="store_true", help="Remove antigravity-pulse from the plugins directory")
    mode.add_argument(
        "--sync-sidecar",
        metavar="PLUGIN_DIR",
        help="Hot-sync sidecars/task_monitor into an existing plugin directory (e.g. task-monitor)",
    )
    mode.add_argument("--update", action="store_true", help="Update existing installation from source/remote")

    parser.add_argument("--remote", action="store_true", help="Force downloading from remote repository archive")
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"GitHub owner/repo (default: {DEFAULT_REPO})")
    parser.add_argument("--version", default="", help="Git branch or tag to install (e.g. main, v1.2.0)")
    parser.add_argument("--archive-url", default="", help="Custom .tar.gz URL or local archive file path")
    parser.add_argument("--sha256", default="", help="Optional expected SHA256 hex digest for archive verification")
    parser.add_argument("--plugins-dir", default="", help="Override Antigravity plugins directory")
    parser.add_argument("--dry-run", action="store_true", help="Preview file operations without writing to disk")
    parser.add_argument("--skip-doctor", action="store_true", help="Skip preflight environment checks")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    plugins_base = Path(os.path.expanduser(args.plugins_dir)).resolve() if args.plugins_dir else _default_plugins_base()

    if args.doctor:
        report = run_doctor(plugins_base, verbose=True)
        return 0 if report["ok"] else 1

    if args.uninstall:
        uninstall_plugin(plugins_base, dry_run=args.dry_run)
        return 0

    if not args.skip_doctor:
        report = run_doctor(plugins_base, verbose=True)
        if not report["ok"]:
            return 1

    local_repo = _detect_local_repo()
    use_remote = bool(args.remote or args.archive_url or args.version or local_repo is None)

    try:
        if use_remote:
            url = _resolve_archive_url(args.repo, args.version or "main", args.archive_url)
            with tempfile.TemporaryDirectory(prefix="ag-pulse-") as tmpdir:
                source_root = _download_and_extract(url, tmpdir, expected_sha256=args.sha256)
                if args.sync_sidecar:
                    sync_sidecar(source_root, plugins_base, args.sync_sidecar, dry_run=args.dry_run)
                else:
                    install_plugin(source_root, plugins_base, dry_run=args.dry_run)
        else:
            if args.sync_sidecar:
                sync_sidecar(local_repo, plugins_base, args.sync_sidecar, dry_run=args.dry_run)
            else:
                install_plugin(local_repo, plugins_base, dry_run=args.dry_run)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
