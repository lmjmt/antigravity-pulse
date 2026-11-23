#!/usr/bin/env bash
set -euo pipefail

# Antigravity Pulse Installer Wrapper (macOS / Linux)
# Works both inside a cloned repository and via:
#   curl -fsSL https://raw.githubusercontent.com/lmjmt/antigravity-pulse/main/scripts/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/lmjmt/antigravity-pulse/main/scripts/install.sh | bash -s -- --version v1.2.0

REPO="${ANTIGRAVITY_PULSE_REPO:-lmjmt/antigravity-pulse}"
REF="${ANTIGRAVITY_PULSE_REF:-main}"

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 (3.9+) is required to install and run Antigravity Pulse." >&2
    exit 1
fi

SCRIPT_SOURCE="${BASH_SOURCE[0]:-}"
if [[ -n "$SCRIPT_SOURCE" && -f "$SCRIPT_SOURCE" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_SOURCE")" && pwd)"
    if [[ -f "$SCRIPT_DIR/install.py" && -f "$SCRIPT_DIR/../plugin.json" ]]; then
        exec python3 "$SCRIPT_DIR/install.py" "$@"
    fi
fi

# Remote pipe mode: fetch install.py into a temp file and run in --remote mode
TMP_INSTALLER="$(mktemp "${TMPDIR:-/tmp}/ag-pulse-install.XXXXXX.py")"
trap 'rm -f "$TMP_INSTALLER"' EXIT

RAW_URL="https://raw.githubusercontent.com/${REPO}/${REF}/scripts/install.py"
CURL_ARGS=(-fsSL)
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
    CURL_ARGS+=(-H "Authorization: Bearer ${GITHUB_TOKEN}")
fi

echo "Fetching Antigravity Pulse installer from ${RAW_URL} ..."
curl "${CURL_ARGS[@]}" "$RAW_URL" -o "$TMP_INSTALLER"
python3 "$TMP_INSTALLER" --remote --repo "$REPO" "$@"
