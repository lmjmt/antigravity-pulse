"""Real-time multi-task monitor, subagent topology evaluator, and hang diagnosis."""

import json
import os
import re
import sqlite3
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

from core.config import get_data_dirs, get_time_range_bounds
from core.formatting import (
    clean_user_prompt,
    extract_generic_body,
    extract_workspace_name,
    format_duration,
    parse_iso,
    parse_step_exit_code,
    stat_sig,
)
from core.i18n import normalize_lang, tr
from core.storage import (
    fetch_merged_conversations,
    find_transcript_path,
    is_session_locked,
    resolve_conversation_dt,
)
from core.swarm import parse_swarm_state


class AntigravityMultiTaskManager:
    """Monitors active/recent sessions, Swarm/subagent trees, and heartbeat anomalies."""

    def __init__(self, stuck_threshold=180, warning_threshold=60, analytics_engine=None):
        self.stuck_threshold = stuck_threshold
        self.warning_threshold = warning_threshold
        self._analytics_engine = analytics_engine
        self._lock = threading.RLock()
        self._tail_cache = {}
        self._steps_full_cache = {}
        self._report_cache = {}

    def get_all_raw_conversations(self, limit=180):
        return fetch_merged_conversations(limit=limit)

    def parse_transcript_tail(self, conversation_id, max_steps=20):
        fpath = find_transcript_path(conversation_id)
        if not fpath or not os.path.exists(fpath):
            return [], None

        try:
            st = os.stat(fpath)
            sig = (st.st_mtime_ns, st.st_size, int(max_steps))
        except OSError:
            with self._lock:
                self._tail_cache.pop(fpath, None)
            return [], None

        with self._lock:
            cached = self._tail_cache.get(fpath)
            if cached and cached[0] == sig:
                return cached[1]

        steps = []
        user_prompt = None
        try:
            with open(fpath, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                buf = min(size, 98304)
                f.seek(size - buf)
                data = f.read().decode("utf-8", errors="ignore")
                lines = [l.strip() for l in data.strip().split(chr(10)) if l.strip()]

                for line in reversed(lines):
                    try:
                        step = json.loads(line)
                        if step.get("type") == "USER_INPUT" and not user_prompt:
                            user_prompt = step.get("content", "")
                        if len(steps) < max_steps:
                            steps.append(step)
                    except Exception:
                        continue
        except Exception:
            pass

        result = (list(reversed(steps)), user_prompt)
        with self._lock:
            self._tail_cache[fpath] = (sig, result)
        return result

    @staticmethod
    def _format_tool_action(tc, lang="zh"):
        """Format a tool_call dictionary into (tool_name, args_preview, full_action)."""
        tool_name = tc.get("name") or ""
        args = tc.get("args") or {}
        if tool_name == "swarm_wait":
            since = args.get("since")
            suffix = f" · after #{since}" if since is not None else ""
            return tool_name, str(since or ""), tr(
                lang,
                f"🐝 休眠等待 Swarm 消息唤醒{suffix}",
                f"🐝 Waiting for Swarm message{suffix}",
            )
        args_preview = (
            args.get("toolSummary")
            or args.get("CommandLine")
            or args.get("Path")
            or args.get("query")
            or args.get("Role")
            or args.get("action")
            or args.get("text")
            or str(args)
        )
        clean_args = str(args_preview).strip().replace(chr(10), " ")[:100]
        return tool_name, clean_args, f"{tool_name}: {clean_args}"

    @classmethod
    def _summarize_step(cls, st, prev_st=None, lang="zh"):
        """Convert a verbose transcript step dictionary into a slim UI-ready summary."""
        stype = st.get("type") or ""
        tool_calls = st.get("tool_calls") or []
        tool_name = None
        clean_args = ""
        exit_code = None
        is_swarm_wait = False
        preview_str = ""
        detail_str = ""

        if tool_calls:
            tc0 = tool_calls[0]
            tool_name, clean_args, _ = cls._format_tool_action(tc0, lang=lang)
            is_swarm_wait = any(tc.get("name") == "swarm_wait" for tc in tool_calls)
            extra = (
                tr(lang, f" (+{len(tool_calls) - 1}个并行调用)", f" (+{len(tool_calls) - 1} parallel)")
                if len(tool_calls) > 1
                else ""
            )
            preview_str = f"{clean_args}{extra}".strip()
            call_lines = []
            for tc in tool_calls:
                t_n = tc.get("name") or ""
                try:
                    t_args = json.dumps(tc.get("args") or {}, ensure_ascii=False, indent=2)
                except Exception:
                    t_args = str(tc.get("args") or {})
                call_lines.append(f"[{t_n}]\n{t_args}")
            thinking = str(st.get("thinking") or "").strip()
            head_th = tr(lang, f"思考摘要: {thinking[:220]}\n\n", f"Thinking: {thinking[:220]}\n\n") if thinking else ""
            detail_str = f"{head_th}" + "\n\n".join(call_lines)
        elif stype in (
            "GENERIC", "RUN_COMMAND", "VIEW_FILE", "CODE_ACTION",
            "GREP_SEARCH", "SEARCH_WEB", "LIST_DIRECTORY",
        ):
            raw_content = str(st.get("content") or "")
            _, clean_body = extract_generic_body(raw_content)
            exit_code = parse_step_exit_code(raw_content)
            prev_tcs = prev_st.get("tool_calls", []) if prev_st else []
            prev_wait = any(tc.get("name") == "swarm_wait" for tc in prev_tcs)
            is_swarm_wait = ("Waiting for a message" in clean_body) or prev_wait
            if is_swarm_wait:
                preview_str = tr(lang, "进入 swarm_wait 等待唤醒", "Entered swarm_wait")
            else:
                trimmed = re.sub(r"^Command exited with code \d+\s*(?:Command output:)?\s*", "", clean_body).strip()
                done_lbl = tr(lang, "已完成", "Completed")
                err_lbl = tr(lang, f"退出码 {exit_code}", f"Exit code {exit_code}")
                preview_str = trimmed or (done_lbl if exit_code in (None, 0) else err_lbl)
            detail_str = raw_content.strip() or clean_body
        elif stype == "USER_INPUT":
            cleaned = clean_user_prompt(st.get("content", ""), max_len=600)
            preview_str = cleaned
            detail_str = cleaned
        elif stype == "ERROR_MESSAGE":
            raw_err = str(st.get("content") or "").strip()
            preview_str = raw_err.replace(chr(10), " ")
            detail_str = raw_err
        else:
            raw_text = str(st.get("content") or st.get("thinking") or "").strip()
            preview_str = raw_text.replace(chr(10), " ") if raw_text else stype
            detail_str = raw_text or stype

        return {
            "step_index": st.get("step_index"),
            "created_at": st.get("created_at"),
            "type": stype,
            "status": st.get("status"),
            "tool_name": tool_name,
            "tool_arg": clean_args,
            "exit_code": exit_code,
            "is_swarm_wait": is_swarm_wait,
            "preview": preview_str[:160],
            "detail": detail_str[:600],
        }

    @classmethod
    def _summarize_steps_list(cls, raw_steps, lang="zh"):
        out = []
        for idx, st in enumerate(raw_steps or []):
            prev_st = raw_steps[idx - 1] if idx > 0 else None
            out.append(cls._summarize_step(st, prev_st=prev_st, lang=lang))
        return out

    def get_subagents(self, parent_conversation_id, swarm_members=None, children_map=None, lang="zh"):
        subagents = []
        seen_cids = set()

        def append_rows(rows):
            for r in rows:
                rcid = r["conversation_id"]
                if rcid in seen_cids:
                    continue
                seen_cids.add(rcid)
                m_meta = swarm_members.get(rcid) if swarm_members else None
                children = self.get_subagents(rcid, swarm_members=swarm_members, children_map=children_map, lang=lang)
                details = self.evaluate_task_node(r, swarm_member_meta=m_meta, include_steps=False, lang=lang)
                subagents.append({
                    "conversation_id": rcid,
                    "agent_name": r.get("agent_name"),
                    "step_count": details.get("step_count", r.get("step_count") or 0),
                    "children": children,
                    "details": details,
                })

        if children_map is not None:
            mem_rows = sorted(
                children_map.get(parent_conversation_id, []),
                key=lambda x: x.get("last_modified_time") or "",
            )
            append_rows(mem_rows)
        else:
            for d in get_data_dirs():
                db = os.path.join(d, "conversation_summaries.db")
                if not os.path.exists(db):
                    continue
                try:
                    conn = sqlite3.connect(db, timeout=3)
                    conn.row_factory = sqlite3.Row
                    c = conn.cursor()
                    c.execute(
                        """
                        SELECT conversation_id, title, status, not_fully_idle, step_count,
                               last_modified_time, workspace_uris, parent_conversation_id, agent_name
                        FROM conversation_summaries
                        WHERE parent_conversation_id = ?
                        ORDER BY last_modified_time ASC
                        """,
                        (parent_conversation_id,),
                    )
                    rows = [dict(r) for r in c.fetchall()]
                    conn.close()
                    append_rows(rows)
                except Exception:
                    pass

        subagents.sort(key=lambda s: (
            not s["details"].get("is_running", False),
            s["details"].get("health") == "KILLED",
            s["details"].get("inactivity_sec", 999999),
            s.get("agent_name") or "",
        ))
        return subagents

    def _inspect_transcript_tail(self, steps, lang="zh"):
        """Extract latest action, thinking, swarm_wait state, timestamp, and step count from transcript tail."""
        idle_action = tr(lang, "空闲就绪", "Idle / Ready")
        if not steps:
            return {
                "last_step": None,
                "last_activity_dt": None,
                "current_action": idle_action,
                "current_tool": None,
                "current_args_preview": "",
                "current_thinking": "",
                "is_swarm_waiting": False,
                "max_step_index": -1,
            }

        last_step = steps[-1]
        max_step_index = -1
        for st in steps:
            sidx = st.get("step_index")
            if isinstance(sidx, int) and sidx > max_step_index:
                max_step_index = sidx

        meaningful = next((s for s in reversed(steps) if s.get("type") != "SYSTEM_MESSAGE"), last_step)
        m_idx = len(steps) - 1 - next((i for i, s in enumerate(reversed(steps)) if s is meaningful), 0)
        prev_step = steps[m_idx - 1] if m_idx > 0 else None

        last_activity_dt = parse_iso(last_step.get("created_at"))
        if meaningful.get("type") == "GENERIC":
            completed_dt, clean_body = extract_generic_body(meaningful.get("content", ""))
            if completed_dt and (not last_activity_dt or completed_dt > last_activity_dt):
                last_activity_dt = completed_dt
        else:
            clean_body = ""

        current_thinking = ""
        for s in (meaningful, last_step):
            if s.get("thinking"):
                current_thinking = str(s["thinking"]).strip().replace(chr(10), " ")[:300]
                break

        current_action = idle_action
        current_tool = None
        current_args_preview = ""
        is_swarm_waiting = False

        stype = meaningful.get("type")
        tool_calls = meaningful.get("tool_calls", [])
        if tool_calls:
            tc = tool_calls[-1]
            current_tool, current_args_preview, current_action = self._format_tool_action(tc, lang=lang)
            if current_tool == "swarm_wait":
                is_swarm_waiting = True
        elif stype == "GENERIC":
            prev_tcs = prev_step.get("tool_calls", []) if prev_step else []
            prev_wait = next((tc for tc in reversed(prev_tcs) if tc.get("name") == "swarm_wait"), None)
            if "Waiting for a message" in clean_body or prev_wait is not None:
                is_swarm_waiting = True
                since = (prev_wait.get("args") or {}).get("since") if prev_wait else None
                suffix = f" · after #{since}" if since is not None else ""
                current_tool = "swarm_wait"
                current_action = tr(lang, f"🐝 休眠等待 Swarm 消息唤醒{suffix}", f"🐝 Waiting for Swarm message{suffix}")
            else:
                prev_tool_name = prev_tcs[-1].get("name") if prev_tcs else ""
                exit_code = parse_step_exit_code(meaningful.get("content", ""))
                if exit_code is not None and exit_code != 0:
                    prefix = tr(
                        lang,
                        f"❌ {prev_tool_name or '命令'} 失败(码 {exit_code}): ",
                        f"❌ {prev_tool_name or 'Command'} failed (code {exit_code}): ",
                    )
                else:
                    prefix = (
                        tr(lang, f"✔ {prev_tool_name} 返回: ", f"✔ {prev_tool_name}: ")
                        if prev_tool_name
                        else tr(lang, "✔ 工具返回: ", "✔ Tool output: ")
                    )
                body_preview = clean_body[:85] if clean_body else tr(lang, "已完成", "Completed")
                current_action = f"{prefix}{body_preview}"
        elif stype == "USER_INPUT":
            current_action = tr(lang, "接收用户指令，等待规划...", "Received prompt, planning...")
        elif stype == "PLANNER_RESPONSE":
            current_action = tr(lang, "生成回复 / 等待交互", "Generating reply / waiting")

        return {
            "last_step": last_step,
            "last_activity_dt": last_activity_dt,
            "current_action": current_action,
            "current_tool": current_tool,
            "current_args_preview": current_args_preview,
            "current_thinking": current_thinking,
            "is_swarm_waiting": is_swarm_waiting,
            "max_step_index": max_step_index,
        }

    def evaluate_task_node(self, conv_dict, swarm_member_meta=None, include_steps=True, lang="zh"):
        lang = normalize_lang(lang)
        cid = conv_dict["conversation_id"]
        status_str = conv_dict.get("status", "")
        not_fully_idle = conv_dict.get("not_fully_idle", 0)

        steps, user_prompt = self.parse_transcript_tail(cid, max_steps=20)
        tail = self._inspect_transcript_tail(steps, lang=lang)
        now_utc = datetime.now(timezone.utc)

        is_killed = bool(swarm_member_meta and swarm_member_meta.get("killed"))
        is_running = (status_str == "CASCADE_RUN_STATUS_RUNNING" or not_fully_idle == 1) and not is_killed
        is_locked = is_session_locked(cid)
        is_swarm_waiting = tail["is_swarm_waiting"]

        inactivity_sec = 0
        if tail["last_activity_dt"]:
            inactivity_sec = max(0, (now_utc - tail["last_activity_dt"]).total_seconds())
        else:
            db_dt = parse_iso(conv_dict.get("last_modified_time"))
            if db_dt:
                inactivity_sec = max(0, (now_utc - db_dt).total_seconds())

        health = "IDLE"
        health_desc = tr(lang, "已完成", "Completed")
        alert_level = "info"

        if is_killed:
            health = "KILLED"
            alert_level = "info"
            health_desc = tr(lang, "已销毁 (Swarm Worker Killed)", "Killed (Swarm Worker)")
        elif is_running:
            if status_str == "CASCADE_RUN_STATUS_IDLE" and not_fully_idle == 1 and is_swarm_waiting:
                health = "SWARM_ACTIVE"
                alert_level = "success"
                health_desc = tr(lang, "🐝 Swarm 协调等待中", "🐝 Swarm Coordinating")
            elif inactivity_sec > self.stuck_threshold:
                health = "STUCK"
                alert_level = "danger"
                health_desc = tr(
                    lang,
                    f"⚠️ 疑似卡死！持续 {format_duration(inactivity_sec)} 无响应",
                    f"⚠️ Possible Stall! Silent for {format_duration(inactivity_sec)}",
                )
            elif inactivity_sec > self.warning_threshold:
                health = "BUSY"
                alert_level = "warning"
                health_desc = tr(lang, f"耗时执行中 ({format_duration(inactivity_sec)})", f"Long step ({format_duration(inactivity_sec)})")
            else:
                health = "RUNNING"
                alert_level = "success"
                health_desc = tr(
                    lang,
                    f"🟢 活跃运行中 (心跳 {format_duration(inactivity_sec)})",
                    f"🟢 Active (beat {format_duration(inactivity_sec)})",
                )
        else:
            last_step = tail["last_step"]
            if is_swarm_waiting:
                health = "SWARM_WAIT"
                alert_level = "info"
                health_desc = tr(lang, "🐝 休眠待命中 (等待 Swarm 消息)", "🐝 Sleeping (swarm_wait)")
            elif last_step and last_step.get("tool_calls"):
                for tc in last_step.get("tool_calls"):
                    if tc.get("name") == "ask_question":
                        health = "WAITING_INPUT"
                        alert_level = "warning"
                        health_desc = tr(lang, "⏸️ 等待用户反馈", "⏸️ Waiting for user input")
                        break

        ws_name = extract_workspace_name(conv_dict.get("workspace_uris", ""))

        raw_title = (conv_dict.get("title") or "").strip()
        if not raw_title and self._analytics_engine is not None:
            _meta = self._analytics_engine._get_transcript_meta_cached(cid, datetime.now().astimezone().tzinfo)
            if _meta and _meta.get("first_user_title"):
                raw_title = _meta["first_user_title"]
        title = raw_title or clean_user_prompt(user_prompt, 64) or tr(lang, f"未命名任务 ({cid[:8]})", f"Untitled Task ({cid[:8]})")
        db_steps = conv_dict.get("step_count", 0) or 0
        effective_steps = max(db_steps, tail["max_step_index"] + 1) if tail["max_step_index"] >= 0 else db_steps

        return {
            "conversation_id": cid,
            "title": title,
            "workspace": ws_name,
            "is_running": is_running,
            "is_locked": is_locked,
            "is_swarm_waiting": is_swarm_waiting,
            "status_str": status_str,
            "step_count": effective_steps,
            "last_modified_time": conv_dict.get("last_modified_time", ""),
            "health": health,
            "alert_level": alert_level,
            "health_desc": health_desc,
            "inactivity_sec": int(inactivity_sec),
            "inactivity_formatted": format_duration(inactivity_sec),
            "current_action": tail["current_action"],
            "current_tool": tail["current_tool"],
            "current_args": tail["current_args_preview"],
            "current_thinking": tail["current_thinking"],
            "recent_steps": self._summarize_steps_list(steps[-15:], lang=lang) if include_steps else [],
            "swarm_member": swarm_member_meta,
        }

    def get_task_steps_window(self, cid, target_step=None, limit=30, lang="zh"):
        """Load summarized steps for any task or subagent with file-signature caching."""
        lang = normalize_lang(lang)
        if not cid:
            return {
                "lang": lang,
                "conversation_id": "",
                "target_step": target_step,
                "total_steps": 0,
                "steps": [],
                "node": None,
            }

        fpath = find_transcript_path(cid)
        all_rows = fetch_merged_conversations(limit=None)
        conv_dict = next((r for r in all_rows if r["conversation_id"] == cid), None) or {
            "conversation_id": cid,
            "title": "",
            "status": "CASCADE_RUN_STATUS_IDLE",
            "not_fully_idle": 0,
            "step_count": 0,
            "last_modified_time": "",
            "workspace_uris": "",
        }
        swarm_meta = None
        parent_cid = conv_dict.get("parent_conversation_id")
        if parent_cid:
            ps = parse_swarm_state(parent_cid)
            if ps:
                swarm_meta = (ps.get("members_by_cid") or {}).get(cid)
        node = self.evaluate_task_node(conv_dict, swarm_member_meta=swarm_meta, include_steps=False, lang=lang)

        if not fpath or not os.path.exists(fpath):
            return {
                "lang": lang,
                "conversation_id": cid,
                "target_step": target_step,
                "total_steps": node.get("step_count", 0),
                "steps": [],
                "node": node,
            }

        cache_key = (fpath, lang)
        sig = stat_sig(fpath)
        summarized_all = None
        if sig is not None:
            with self._lock:
                cached = self._steps_full_cache.get(cache_key)
                if cached and cached[0] == sig:
                    summarized_all = cached[1]

        if summarized_all is None:
            raw_steps = []
            try:
                with open(fpath, "rb") as fp:
                    for ln in fp:
                        s = ln.strip()
                        if not s:
                            continue
                        try:
                            raw_steps.append(json.loads(s.decode("utf-8", errors="ignore")))
                        except Exception:
                            continue
            except Exception:
                pass
            summarized_all = self._summarize_steps_list(raw_steps, lang=lang)
            if sig is not None:
                with self._lock:
                    self._steps_full_cache[cache_key] = (sig, summarized_all)

        total = len(summarized_all)
        limit = max(5, min(int(limit or 30), 80))
        if total == 0:
            window_steps = []
        elif target_step is not None:
            match_idx = None
            best_dist = None
            for idx, st in enumerate(summarized_all):
                sidx = st.get("step_index")
                if isinstance(sidx, int):
                    if sidx == target_step:
                        match_idx = idx
                        break
                    dist = abs(sidx - target_step)
                    if best_dist is None or dist < best_dist:
                        best_dist = dist
                        match_idx = idx
            if match_idx is None:
                match_idx = min(max(0, int(target_step)), total - 1)
            half = limit // 2
            start_i = max(0, match_idx - half)
            end_i = min(total, start_i + limit)
            start_i = max(0, end_i - limit)
            window_steps = summarized_all[start_i:end_i]
        else:
            window_steps = summarized_all[-limit:]

        node["step_count"] = max(node.get("step_count", 0), total)
        return {
            "lang": lang,
            "conversation_id": cid,
            "target_step": target_step,
            "total_steps": node["step_count"],
            "steps": window_steps,
            "node": node,
        }

    def _flatten_subagents(self, subagents):
        out = []
        for s in subagents or []:
            out.append(s)
            if s.get("children"):
                out.extend(self._flatten_subagents(s["children"]))
        return out

    def _apply_cluster_health(self, eval_node, subagents, swarm_state, lang="zh"):
        """Aggregate subagent/Swarm worker heartbeats & board posts onto the root task."""
        descendants = self._flatten_subagents(subagents)
        is_swarm = bool(swarm_state and swarm_state.get("is_swarm"))

        if not is_swarm and not descendants:
            eval_node["swarm"] = None
            return eval_node

        running_workers = [d for d in descendants if d["details"].get("is_running")]
        healthy_running = [d for d in running_workers if d["details"].get("inactivity_sec", 999999) <= self.stuck_threshold]
        waiting_workers = [d for d in descendants if d["details"].get("health") == "SWARM_WAIT"]
        killed_workers = [d for d in descendants if d["details"].get("health") == "KILLED"]
        stuck_workers = [d for d in descendants if d["details"].get("health") == "STUCK"]

        latest_posts = swarm_state.get("latest_board_posts", []) if swarm_state else []
        board_count = swarm_state.get("board_count", 0) if swarm_state else 0
        latest_board_age = swarm_state.get("latest_board_age_sec") if swarm_state else None

        eval_node["swarm"] = {
            "is_swarm": is_swarm,
            "swarm_title": swarm_state.get("swarm_title") if swarm_state else None,
            "total_workers": len(descendants),
            "active_workers": len(running_workers),
            "waiting_workers": len(waiting_workers),
            "killed_workers": len(killed_workers),
            "stuck_workers": len(stuck_workers),
            "board_count": board_count,
            "latest_board_posts": latest_posts,
        }

        if not eval_node["is_running"]:
            return eval_node

        candidate_ages = [eval_node["inactivity_sec"]]
        for d in running_workers + waiting_workers:
            candidate_ages.append(d["details"].get("inactivity_sec", eval_node["inactivity_sec"]))
        if latest_board_age is not None:
            candidate_ages.append(latest_board_age)
        cluster_age = min(candidate_ages)

        board_hint = ""
        if latest_posts:
            lp = latest_posts[0]
            board_hint = tr(
                lang,
                f" · 最新板消息 #{lp.get('seq')} ({lp.get('agent')})",
                f" · board post #{lp.get('seq')} ({lp.get('agent')})",
            )

        if healthy_running:
            eval_node["inactivity_sec"] = int(cluster_age)
            eval_node["inactivity_formatted"] = format_duration(cluster_age)
            eval_node["alert_level"] = "success"
            if is_swarm:
                eval_node["health"] = "SWARM_ACTIVE"
                eval_node["health_desc"] = tr(
                    lang,
                    f"🐝 Swarm 协作运行中 ({len(healthy_running)} 活跃 / {len(waiting_workers)} 休眠 / 共 {len(descendants)} 成员)",
                    f"🐝 Swarm Active ({len(healthy_running)} running / {len(waiting_workers)} sleeping / {len(descendants)} total)",
                )
                if eval_node.get("is_swarm_waiting"):
                    eval_node["current_action"] = tr(
                        lang,
                        f"🐝 协调等待中：{len(healthy_running)} 个 Worker 活跃执行{board_hint}",
                        f"🐝 Coordinating: {len(healthy_running)} workers active{board_hint}",
                    )
            else:
                eval_node["health"] = "RUNNING"
                eval_node["health_desc"] = tr(
                    lang,
                    f"🟢 主从协同运行中 ({len(healthy_running)} 子代理活跃)",
                    f"🟢 Running ({len(healthy_running)} subagents active)",
                )
        elif running_workers:
            eval_node["inactivity_sec"] = int(cluster_age)
            eval_node["inactivity_formatted"] = format_duration(cluster_age)
            if cluster_age <= self.stuck_threshold:
                eval_node["health"] = "SWARM_ACTIVE" if is_swarm else "RUNNING"
                eval_node["alert_level"] = "success"
                eval_node["health_desc"] = tr(
                    lang,
                    f"🐝 Swarm 协作运行中 (消息板活跃 {format_duration(cluster_age)} 前)",
                    f"🐝 Swarm Active (board active {format_duration(cluster_age)} ago)",
                )
            else:
                eval_node["health"] = "STUCK"
                eval_node["alert_level"] = "danger"
                eval_node["health_desc"] = tr(
                    lang,
                    f"⚠️ Swarm 阻塞！活跃成员均已无响应 {format_duration(cluster_age)}",
                    f"⚠️ Swarm Stalled! Workers silent for {format_duration(cluster_age)}",
                )
        elif is_swarm and eval_node.get("is_swarm_waiting"):
            eval_node["inactivity_sec"] = int(cluster_age)
            eval_node["inactivity_formatted"] = format_duration(cluster_age)
            if cluster_age <= self.stuck_threshold:
                eval_node["health"] = "SWARM_ACTIVE"
                eval_node["alert_level"] = "info"
                eval_node["health_desc"] = tr(
                    lang,
                    f"🐝 Swarm 轮次切换中 ({len(waiting_workers)} 休眠 / 最近动态 {format_duration(cluster_age)} 前)",
                    f"🐝 Swarm Transition ({len(waiting_workers)} sleeping / active {format_duration(cluster_age)} ago)",
                )
            else:
                eval_node["health"] = "SWARM_WAIT"
                eval_node["alert_level"] = "warning"
                eval_node["health_desc"] = tr(
                    lang,
                    f"🐝 Swarm 全员休眠待命中 ({len(waiting_workers)} 成员等待唤醒, 已静默 {format_duration(cluster_age)})",
                    f"🐝 Swarm Sleeping ({len(waiting_workers)} waiting, silent {format_duration(cluster_age)})",
                )
                eval_node["current_action"] = tr(
                    lang,
                    f"🐝 协调器与成员均处于 swarm_wait 等待唤醒{board_hint}",
                    f"🐝 Coordinator & workers in swarm_wait{board_hint}",
                )

        return eval_node

    def collect_multi_task_report(self, focused_cid=None, time_range="all", lang="zh"):
        lang = normalize_lang(lang)
        range_key, _, now_local, start_utc, range_label, _ = get_time_range_bounds(time_range, lang=lang)
        now_ts = time.time()
        cache_key = (range_key, focused_cid, lang)
        with self._lock:
            cached = self._report_cache.get(cache_key)
            if cached and (now_ts - cached[0] < 1.0):
                return cached[1]

        raw_convs = self.get_all_raw_conversations(limit=None)
        root_convs = []
        children_map = defaultdict(list)
        for c in raw_convs:
            pid = c.get("parent_conversation_id")
            if pid:
                children_map[pid].append(c)
            else:
                root_convs.append(c)

        local_tz = now_local.tzinfo
        ana_obj = self._analytics_engine
        if start_utc is not None:
            filtered_roots = []
            for c in root_convs:
                is_run = (c.get("status") == "CASCADE_RUN_STATUS_RUNNING" or c.get("not_fully_idle") == 1)
                eff_dt = resolve_conversation_dt(c["conversation_id"], c.get("last_modified_time"), local_tz, ana_obj)
                if is_run or (eff_dt and eff_dt.year >= 2000 and eff_dt >= start_utc):
                    filtered_roots.append((1 if is_run else 0, eff_dt.timestamp() if eff_dt else 0.0, c))
            filtered_roots.sort(key=lambda item: (item[0], item[1]), reverse=True)
            root_convs = [item[2] for item in filtered_roots]

        target_convs = list(root_convs[:45])
        if focused_cid and all(c["conversation_id"] != focused_cid for c in target_convs):
            for c in root_convs[45:]:
                if c["conversation_id"] == focused_cid:
                    target_convs.append(c)
                    break

        evaluated_tasks = []
        for c in target_convs:
            cid = c["conversation_id"]
            swarm_state = parse_swarm_state(cid)
            swarm_members = swarm_state["members_by_cid"] if swarm_state else None
            coord_meta = swarm_members.get(cid) if swarm_members else None
            is_run_hint = (c.get("status") == "CASCADE_RUN_STATUS_RUNNING" or c.get("not_fully_idle") == 1)

            eval_node = self.evaluate_task_node(
                c,
                swarm_member_meta=coord_meta,
                include_steps=(cid == focused_cid or is_run_hint),
                lang=lang,
            )
            subagents = self.get_subagents(cid, swarm_members=swarm_members, children_map=children_map, lang=lang)
            eval_node["subagents"] = subagents
            eval_node["subagents_count"] = len(subagents)
            self._apply_cluster_health(eval_node, subagents, swarm_state, lang=lang)
            evaluated_tasks.append(eval_node)

        running_tasks = [t for t in evaluated_tasks if t["is_running"]]
        waiting_tasks = [t for t in evaluated_tasks if t["health"] == "WAITING_INPUT"]
        idle_tasks = [t for t in evaluated_tasks if not t["is_running"] and t["health"] != "WAITING_INPUT"]
        stuck_tasks = [t for t in evaluated_tasks if t["health"] == "STUCK"]

        focused_task = None
        if focused_cid:
            matches = [t for t in evaluated_tasks if t["conversation_id"] == focused_cid]
            if matches:
                focused_task = matches[0]

        if not focused_task:
            if running_tasks:
                focused_task = running_tasks[0]
            elif evaluated_tasks:
                focused_task = evaluated_tasks[0]

        if focused_task and not focused_task.get("recent_steps"):
            f_steps, _ = self.parse_transcript_tail(focused_task["conversation_id"], max_steps=20)
            focused_task["recent_steps"] = self._summarize_steps_list(f_steps[-15:], lang=lang)

        result = {
            "lang": lang,
            "time_range": range_key,
            "range_label": range_label,
            "summary": {
                "total_count": len(evaluated_tasks),
                "matched_total": len(root_convs),
                "running_count": len(running_tasks),
                "waiting_count": len(waiting_tasks),
                "idle_count": len(idle_tasks),
                "stuck_count": len(stuck_tasks),
            },
            "focused_cid": focused_task["conversation_id"] if focused_task else None,
            "focused_task": {"conversation_id": focused_task["conversation_id"]} if focused_task else None,
            "all_tasks": evaluated_tasks,
            "has_stuck": len(stuck_tasks) > 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._report_cache[cache_key] = (now_ts, result)
        return result
