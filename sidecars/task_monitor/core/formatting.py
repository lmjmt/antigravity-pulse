"""Formatting, timestamp parsing, workspace extraction, and prompt cleaning utilities."""

import os
import re
import urllib.parse
from datetime import datetime, timezone

_HOME_SKIP_NAMES = {
    "Users",
    "home",
    "root",
    os.path.basename(os.path.expanduser("~")),
}


def parse_iso(dt_str):
    """Parse an ISO-8601 or SQLite UTC datetime string into an aware datetime object."""
    if not dt_str:
        return None
    normalized = str(dt_str).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        try:
            return datetime.strptime(normalized.split(".")[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except Exception:
            return None


def parse_local_timestamp(ts_str):
    """Parse board.jsonl local wall-clock timestamp ('YYYY-MM-DD HH:MM:SS') into UTC."""
    if not ts_str:
        return None
    try:
        local_tz = datetime.now().astimezone().tzinfo
        dt = datetime.strptime(ts_str.strip()[:19], "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=local_tz).astimezone(timezone.utc)
    except Exception:
        return parse_iso(ts_str)


def format_tokens(num):
    """Format token or call count into compact human-readable K/M/B strings."""
    if num is None:
        return "0"
    if num >= 1e9:
        return f"{num / 1e9:.1f}B"
    if num >= 1e6:
        return f"{num / 1e6:.1f}M"
    if num >= 1e3:
        return f"{num / 1e3:.1f}k"
    return str(int(num))


def format_duration(seconds):
    """Format duration in seconds into concise s/m/h units."""
    if seconds is None or seconds < 0:
        return "0s"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m{s}s" if s > 0 else f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h{m}m"


def stat_sig(path):
    """Return (st_mtime_ns, st_size) signature for cache invalidation, or None."""
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def extract_workspace_name(ws_uris):
    """Extract readable workspace folder name from serialized workspace URIs."""
    if not ws_uris:
        return "Default workspace"
    clean_ws = str(ws_uris).replace("file://", "").replace("[", "").replace("]", "").replace('"', "").strip()
    if not clean_ws:
        return "Default workspace"
    clean_ws = urllib.parse.unquote(clean_ws.split(",")[0].strip().rstrip("/\\"))
    bname = os.path.basename(clean_ws)
    if bname and bname not in _HOME_SKIP_NAMES:
        return bname
    return "Default workspace"


def extract_generic_body(content):
    """Strip tool result Created/Completed At metadata headers and return (completed_dt, clean_body)."""
    if not content:
        return None, ""
    completed_dt = None
    lines = str(content).splitlines()
    idx = 0
    while idx < len(lines) and idx < 4:
        line = lines[idx].strip()
        if line.startswith("Created At:"):
            idx += 1
        elif line.startswith("Completed At:"):
            completed_dt = parse_iso(line[len("Completed At:"):].strip())
            idx += 1
        else:
            break
    body = " ".join(l.strip() for l in lines[idx:] if l.strip())
    return completed_dt, body


def parse_step_exit_code(content):
    """Extract numeric exit code from command tool output content if present."""
    if not content:
        return None
    m = re.search(r"Command exited with code (\d+)", str(content))
    return int(m.group(1)) if m else None


def clean_user_prompt(txt, max_len=90):
    """Strip prompt XML wrappers and normalize whitespace to a single-line preview."""
    if not txt:
        return ""
    cleaned = re.sub(
        r"<USER_REQUEST>|<(?:ADDITIONAL_METADATA|USER_SETTINGS_CHANGE|USER_SETTINGS_CONTEXT|SYSTEM_CONTEXT|MEMORY_CONTEXT)[^>]*>.*?(?:</(?:ADDITIONAL_METADATA|USER_SETTINGS_CHANGE|USER_SETTINGS_CONTEXT|SYSTEM_CONTEXT|MEMORY_CONTEXT)>|$)|<!--.*?-->",
        "",
        str(txt),
        flags=re.DOTALL,
    )
    cleaned = cleaned.replace("</USER_REQUEST>", "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if max_len and len(cleaned) > max_len:
        return cleaned[:max_len] + "..."
    return cleaned
