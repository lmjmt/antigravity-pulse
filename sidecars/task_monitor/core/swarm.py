"""Swarm member roster and message-board state parser with signature caching."""

import glob
import json
import os
import threading
import time

from core.config import get_brain_dirs
from core.formatting import parse_local_timestamp, stat_sig
from core.models import normalize_model_name
from core.storage import find_brain_subdir

SWARM_CACHE_LOCK = threading.RLock()
SWARM_STATE_CACHE = {}
SWARM_MODEL_MAP_CACHE = {"sig": None, "map": {}}


def get_swarm_model_map():
    """Return cached {conversation_id: normalized_model} across all swarm members.json files."""
    paths = []
    for b_dir in get_brain_dirs():
        if os.path.exists(b_dir):
            paths.extend(glob.glob(os.path.join(b_dir, "*", ".system_generated", "swarm", "members.json")))
    paths.sort()

    sigs = []
    for fp in paths:
        try:
            st = os.stat(fp)
            sigs.append((fp, st.st_mtime_ns, st.st_size))
        except OSError:
            pass
    sig = tuple(sigs)

    with SWARM_CACHE_LOCK:
        if SWARM_MODEL_MAP_CACHE["sig"] == sig and SWARM_MODEL_MAP_CACHE["sig"] is not None:
            return dict(SWARM_MODEL_MAP_CACHE["map"])

    mapping = {}
    for fp, _, _ in sig:
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            members = data.get("members") or {}
            if isinstance(members, dict):
                for info in members.values():
                    if not isinstance(info, dict):
                        continue
                    mcid = info.get("conversation_id")
                    mod = normalize_model_name(info.get("applied_model") or info.get("desired_model"))
                    if mcid and mod:
                        mapping[mcid] = mod
        except Exception:
            pass

    with SWARM_CACHE_LOCK:
        SWARM_MODEL_MAP_CACHE["sig"] = sig
        SWARM_MODEL_MAP_CACHE["map"] = mapping
        return dict(mapping)


def parse_swarm_state(cid):
    """Read and file-signature-cache native Swarm metadata (members.json, board.jsonl)."""
    swarm_dir = find_brain_subdir(cid, ".system_generated", "swarm")
    if not swarm_dir:
        return None

    members_path = os.path.join(swarm_dir, "members.json")
    board_path = os.path.join(swarm_dir, "board.jsonl")
    sig = (stat_sig(members_path), stat_sig(board_path))
    if sig == (None, None):
        with SWARM_CACHE_LOCK:
            SWARM_STATE_CACHE.pop(cid, None)
        return None

    base = None
    with SWARM_CACHE_LOCK:
        cached = SWARM_STATE_CACHE.get(cid)
        if cached and cached[0] == sig:
            base = cached[1]

    if base is None:
        members_by_cid = {}
        swarm_title = None
        if os.path.exists(members_path):
            try:
                with open(members_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                swarm_title = data.get("title")
                for mname, info in (data.get("members") or {}).items():
                    if not isinstance(info, dict):
                        continue
                    mcid = info.get("conversation_id")
                    if mcid:
                        members_by_cid[mcid] = {
                            "name": mname,
                            "role": info.get("role", "worker"),
                            "model": info.get("applied_model") or info.get("desired_model") or "",
                            "phase": info.get("phase") or info.get("desired_state") or "",
                            "wake_mode": info.get("wake_mode", ""),
                            "killed": bool(info.get("killed", False)),
                            "owner": info.get("owner", ""),
                            "workspace_mode": info.get("workspace_mode", "inherit"),
                        }
            except Exception:
                pass

        cached_posts = []
        board_count = 0
        if os.path.exists(board_path):
            try:
                with open(board_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = [l.strip() for l in f if l.strip()]
                board_count = len(lines)
                for ln in reversed(lines[-4:]):
                    try:
                        item = json.loads(ln)
                    except Exception:
                        continue
                    post_dt = parse_local_timestamp(item.get("time"))
                    post_epoch = post_dt.timestamp() if post_dt else None
                    txt = str(item.get("text", "")).strip().replace(chr(10), " ")
                    cached_posts.append({
                        "seq": item.get("seq"),
                        "agent": item.get("agent", "unknown"),
                        "time": item.get("time", ""),
                        "_epoch": post_epoch,
                        "text_preview": (txt[:140] + "...") if len(txt) > 140 else txt,
                    })
            except Exception:
                pass

        base = {
            "swarm_title": swarm_title,
            "members_by_cid": members_by_cid,
            "board_count": board_count,
            "cached_posts": cached_posts,
        }
        with SWARM_CACHE_LOCK:
            SWARM_STATE_CACHE[cid] = (sig, base)

    now_epoch = time.time()
    latest_posts = []
    latest_board_age_sec = None
    for cp in base["cached_posts"]:
        ep = cp["_epoch"]
        age_sec = int(max(0, now_epoch - ep)) if ep is not None else None
        if latest_board_age_sec is None and age_sec is not None:
            latest_board_age_sec = age_sec
        latest_posts.append({
            "seq": cp["seq"],
            "agent": cp["agent"],
            "time": cp["time"],
            "age_sec": age_sec,
            "text_preview": cp["text_preview"],
        })

    return {
        "is_swarm": True,
        "swarm_title": base["swarm_title"],
        "members_by_cid": base["members_by_cid"],
        "board_count": base["board_count"],
        "latest_board_age_sec": latest_board_age_sec,
        "latest_board_posts": latest_posts,
    }
