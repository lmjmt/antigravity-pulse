"""SQLite conversation summaries, transcript discovery, lock checks, and timestamp resolution."""

import os
import sqlite3
import threading
from datetime import datetime, timezone

from core.config import get_brain_dirs, get_data_dirs, get_presence_dirs
from core.formatting import parse_iso

DB_CACHE_LOCK = threading.RLock()
DB_CONVS_CACHE = {"sig": None, "rows": []}


def _get_db_files_sig():
    sigs = []
    for d in get_data_dirs():
        for fname in ("conversation_summaries.db", "conversation_summaries.db-wal"):
            fp = os.path.join(d, fname)
            try:
                st = os.stat(fp)
                sigs.append((fp, st.st_mtime_ns, st.st_size))
            except OSError:
                sigs.append((fp, 0, 0))
    return tuple(sigs)


def fetch_merged_conversations(limit=None):
    """Fetch, deduplicate, and signature-cache conversation_summaries across all data dirs."""
    sig = _get_db_files_sig()
    with DB_CACHE_LOCK:
        if DB_CONVS_CACHE["sig"] == sig and DB_CONVS_CACHE["rows"]:
            cached_rows = DB_CONVS_CACHE["rows"]
            return list(cached_rows[:int(limit)]) if limit is not None else list(cached_rows)

    merged = {}
    sql = """
        SELECT conversation_id, title, status, not_fully_idle, step_count,
               last_modified_time, workspace_uris, parent_conversation_id, agent_name
        FROM conversation_summaries
        ORDER BY last_modified_time DESC
    """
    for d in get_data_dirs():
        db = os.path.join(d, "conversation_summaries.db")
        if not os.path.exists(db):
            continue
        try:
            conn = sqlite3.connect(db, timeout=4)
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            c.execute(sql)
            for r in c.fetchall():
                cid = r["conversation_id"]
                if cid not in merged or (r["last_modified_time"] or "") > (merged[cid].get("last_modified_time") or ""):
                    row_dict = dict(r)
                    row_dict["data_dir"] = d
                    merged[cid] = row_dict
            conn.close()
        except Exception:
            pass

    rows = list(merged.values())
    rows.sort(key=lambda x: x.get("last_modified_time") or "", reverse=True)
    with DB_CACHE_LOCK:
        DB_CONVS_CACHE["sig"] = sig
        DB_CONVS_CACHE["rows"] = rows
    return list(rows[:int(limit)]) if limit is not None else list(rows)


def find_brain_subdir(cid, *parts):
    """Locate a path inside any configured brain directory for a conversation."""
    if not cid:
        return None
    for b in get_brain_dirs():
        p = os.path.join(b, str(cid), *parts)
        if os.path.exists(p):
            return p
    return None


def find_transcript_path(cid):
    """Locate transcript.jsonl for a conversation ID across brain directories."""
    return find_brain_subdir(cid, ".system_generated", "logs", "transcript.jsonl")


def resolve_conversation_dt(cid, lmt_str, local_tz=None, analytics_obj=None):
    """Resolve effective UTC timestamp, falling back to transcript metadata/mtime when DB has 0001-01-01."""
    dt = parse_iso(lmt_str)
    if dt and dt.year >= 2000:
        return dt.astimezone(timezone.utc)
    if local_tz is None:
        local_tz = datetime.now().astimezone().tzinfo
    if analytics_obj is not None and cid:
        meta = analytics_obj._get_transcript_meta_cached(cid, local_tz)
        if meta and meta.get("last_dt_utc") and meta["last_dt_utc"].year >= 2000:
            return meta["last_dt_utc"].astimezone(timezone.utc)
    tpath = find_transcript_path(cid)
    if tpath and os.path.exists(tpath):
        try:
            return datetime.fromtimestamp(os.path.getmtime(tpath), tz=timezone.utc)
        except Exception:
            pass
    return None


def is_session_locked(cid):
    """Check whether a session holds an active runtime presence lock file."""
    if not cid:
        return False
    for pr in get_presence_dirs():
        lock_file = os.path.join(pr, f"{cid}.lock")
        if os.path.exists(lock_file):
            return True
    return False
