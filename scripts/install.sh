#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGINS_BASE="${ANTIGRAVITY_PLUGINS_DIR:-$HOME/.gemini/config/plugins}"

usage() {
    cat <<EOF
Usage:
  ./scripts/install.sh                         Install antigravity-pulse into $PLUGINS_BASE/antigravity-pulse
  ./scripts/install.sh --sync-sidecar <dir>    Sync sidecars/task_monitor/ into an existing plugin directory (e.g. task-monitor)
EOF
}

sync_dir() {
    local src="$1"
    local dst="$2"
    mkdir -p "$dst"
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --delete \
            --exclude '__pycache__' \
            --exclude '*.pyc' \
            --exclude '.DS_Store' \
            "$src/" "$dst/"
    else
        rm -rf "$dst"
        mkdir -p "$dst"
        cp -R "$src/." "$dst/"
        find "$dst" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
    fi
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

if [[ "${1:-}" == "--sync-sidecar" ]]; then
    TARGET_PLUGIN="${2:-}"
    if [[ -z "$TARGET_PLUGIN" ]]; then
        echo "Error: missing <plugin-dir> argument for --sync-sidecar" >&2
        usage
        exit 1
    fi
    TARGET_SIDECAR="$PLUGINS_BASE/$TARGET_PLUGIN/sidecars/task_monitor"
    if [[ ! -d "$PLUGINS_BASE/$TARGET_PLUGIN" ]]; then
        echo "Error: target plugin directory not found: $PLUGINS_BASE/$TARGET_PLUGIN" >&2
        exit 1
    fi
    echo "Syncing modular sidecar into $TARGET_SIDECAR ..."
    # Sync code subdirectories + monitor_core.py + server.py + sidecar.json
    sync_dir "$REPO_ROOT/sidecars/task_monitor/core" "$TARGET_SIDECAR/core"
    sync_dir "$REPO_ROOT/sidecars/task_monitor/web" "$TARGET_SIDECAR/web"
    cp "$REPO_ROOT/sidecars/task_monitor/monitor_core.py" "$TARGET_SIDECAR/monitor_core.py"
    cp "$REPO_ROOT/sidecars/task_monitor/server.py" "$TARGET_SIDECAR/server.py"
    cp "$REPO_ROOT/sidecars/task_monitor/sidecar.json" "$TARGET_SIDECAR/sidecar.json"
    echo "Done! Sidecar code synced (press Cmd+R in side pane to hot-reload ui/backend)."
    exit 0
fi

TARGET_DIR="$PLUGINS_BASE/antigravity-pulse"
echo "Installing antigravity-pulse plugin to $TARGET_DIR ..."
mkdir -p "$TARGET_DIR"
for sub in hooks rules skills sidecars; do
    sync_dir "$REPO_ROOT/$sub" "$TARGET_DIR/$sub"
done
cp "$REPO_ROOT/plugin.json" "$TARGET_DIR/plugin.json"
cp "$REPO_ROOT/hooks.json" "$TARGET_DIR/hooks.json"
cp "$REPO_ROOT/README.md" "$TARGET_DIR/README.md"
echo "Installed cleanly at $TARGET_DIR"
