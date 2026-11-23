#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "[1/4] Compiling Python bytecode..."
python3 -m compileall -q sidecars/task_monitor tests hooks

echo "[2/4] Checking frontend ES6 syntax..."
if command -v node >/dev/null 2>&1; then
    for js_file in sidecars/task_monitor/web/js/*.js; do
        node --check "$js_file"
    done
    echo "  -> all $(ls sidecars/task_monitor/web/js/*.js | wc -l | tr -d ' ') JS modules valid"
else
    echo "  -> node not found, skipping JS syntax check"
fi

echo "[3/4] Running unit test suite..."
python3 -m unittest discover -s tests -v

echo "[4/4] Running generic portability & privacy scan..."
python3 - <<'PY'
import pathlib, re, sys

home_pat = re.compile(r"(/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/|C:\\\\Users\\\\)")
uuid_pat = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
email_pat = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

hits = []
for p in sorted(pathlib.Path(".").rglob("*")):
    if not p.is_file() or ".git" in p.parts or "__pycache__" in p.parts:
        continue
    rel = str(p)
    text = p.read_text(encoding="utf-8", errors="ignore")
    for idx, line in enumerate(text.splitlines(), 1):
        if home_pat.search(line):
            hits.append(f"{rel}:{idx}: hardcoded user home path")
        if rel.startswith(("sidecars/", "hooks/")) and uuid_pat.search(line):
            hits.append(f"{rel}:{idx}: hardcoded UUID in runtime code")
        for em in email_pat.findall(line):
            if not em.endswith(("@example.com", "@users.noreply.github.com")):
                hits.append(f"{rel}:{idx}: email literal {em}")

if hits:
    print("Blocked portability/privacy matches found:")
    for h in hits:
        print(" ", h)
    sys.exit(1)
print("  -> clean (0 hits)")
PY

echo "ALL CHECKS PASSED"
