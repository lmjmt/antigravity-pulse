"""Global token/cost/duration/model analytics and session cards aggregator."""

import glob
import json
import os
import re
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from core.config import (
    CONTEXT_WINDOW_TOKENS,
    DEFAULT_OUTPUT_SPEED,
    PRICE_CACHE_PER_M,
    PRICE_INPUT_PER_M,
    PRICE_OUTPUT_PER_M,
    get_brain_dirs,
    get_time_range_bounds,
)
from core.formatting import (
    clean_user_prompt,
    extract_workspace_name,
    format_duration,
    format_tokens,
    parse_iso,
)
from core.i18n import (
    format_month_label,
    format_relative_time,
    normalize_lang,
    tr,
)
from core.models import (
    FAMILY_COLORS,
    MODEL_PALETTE,
    MODEL_SEL_RE,
    get_model_family,
    get_unknown_model_label,
    normalize_model_name,
)
from core.storage import fetch_merged_conversations, find_transcript_path, resolve_conversation_dt
from core.swarm import get_swarm_model_map
from core.timeline import analyze_context_timeline as _analyze_timeline


class AntigravityAnalytics:
    """Computes aggregated KPIs, model breakdowns, heatmaps, session overviews, and timelines."""

    def __init__(self):
        self._lock = threading.RLock()
        self._range_caches = {}
        self._sessions_caches = {}
        self._file_step_cache = {}
        self._file_meta_cache = {}
        self._timeline_cache = {}
        self.cache_ttl = 3.0

    def _parse_transcript_steps_cached(self, fpath, local_tz):
        """Incrementally parse transcript steps & session overview metadata keyed by (mtime_ns, size)."""
        try:
            st = os.stat(fpath)
            sig = (st.st_mtime_ns, st.st_size)
        except OSError:
            with self._lock:
                self._file_step_cache.pop(fpath, None)
                self._file_meta_cache.pop(fpath, None)
            return []

        with self._lock:
            cached = self._file_step_cache.get(fpath)
            if cached and cached[0] == sig and fpath in self._file_meta_cache:
                return cached[1]

        conv_id = fpath.split(os.sep)[-4]
        steps_out = []
        turns = 0
        total_steps = 0
        first_user_title = ""
        last_user_msg = ""
        first_dt = None
        last_dt = None
        last_dt_msg = None
        last_stype = None
        sum_in = 0
        sum_out = 0
        sum_cache = 0
        last_ctx_tokens = 0
        has_billing_tokens = False
        est_text_tokens = 0
        segment_text_tokens = 0
        cur_settings_model = ""
        first_from_model = ""
        conv_model_counts = defaultdict(int)

        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as fp:
                for line in fp:
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    total_steps += 1
                    stype = d.get("type")
                    raw_content = d.get("content")
                    if isinstance(raw_content, str) and "Model Selection" in raw_content:
                        for ms_match in MODEL_SEL_RE.finditer(raw_content):
                            frm = normalize_model_name(ms_match.group(1))
                            to = normalize_model_name(ms_match.group(2))
                            if not first_from_model and not cur_settings_model and frm:
                                first_from_model = frm
                            if to:
                                cur_settings_model = to

                    dt = parse_iso(d.get("created_at"))
                    if not dt:
                        continue
                    if first_dt is None:
                        first_dt = dt
                    last_dt_msg = dt
                    dt_local = dt.astimezone(local_tz)
                    epoch = dt_local.timestamp()
                    day_key = dt_local.strftime("%Y-%m-%d")
                    hour_int = dt_local.hour

                    in_tok = d.get("input_tokens", 0) or 0
                    out_tok = d.get("output_tokens", 0) or 0
                    cache_tok = d.get("cache_read_tokens", 0) or 0
                    if in_tok > 0 or out_tok > 0 or cache_tok > 0:
                        has_billing_tokens = True
                        sum_in += in_tok
                        sum_out += out_tok
                        sum_cache += cache_tok
                        if in_tok > 0:
                            last_ctx_tokens = in_tok + cache_tok

                    wait_diff = 0.0
                    exec_diff = 0.0
                    param_diff = 0.0
                    if last_dt is not None:
                        diff = (dt - last_dt).total_seconds()
                        if 0 < diff < 600:
                            if last_stype == "USER_INPUT" and stype == "PLANNER_RESPONSE":
                                wait_diff = diff
                            elif last_stype == "PLANNER_RESPONSE" and stype in (
                                "GENERIC", "VIEW_FILE", "RUN_COMMAND", "CODE_ACTION",
                                "GREP_SEARCH", "SEARCH_WEB", "LIST_DIRECTORY",
                            ):
                                exec_diff = diff
                            elif last_stype in (
                                "GENERIC", "VIEW_FILE", "RUN_COMMAND", "CODE_ACTION",
                                "GREP_SEARCH", "SEARCH_WEB", "LIST_DIRECTORY",
                            ) and stype == "PLANNER_RESPONSE":
                                param_diff = min(diff * 0.3, 10.0)
                                wait_diff = max(diff * 0.7, 0.0)
                    last_dt = dt
                    last_stype = stype

                    user_tok = 0
                    th_tok = 0
                    rep_tok = 0
                    tool_out_tok = 0
                    tools = []
                    cmds = []
                    skills = []

                    if stype == "USER_INPUT":
                        turns += 1
                        raw_u = str(d.get("content", ""))
                        user_tok = int(len(raw_u) * 0.3)
                        if "<CONTEXT_SUMMARY>" in raw_u:
                            segment_text_tokens = 0
                        else:
                            cleaned_u = clean_user_prompt(raw_u, max_len=90)
                            if cleaned_u and not first_user_title:
                                first_user_title = cleaned_u[:64]
                            if cleaned_u:
                                last_user_msg = cleaned_u
                    elif stype == "PLANNER_RESPONSE":
                        th = d.get("thinking", "")
                        if th:
                            th_tok = int(len(th) * 0.3)
                        co = d.get("content", "")
                        if co:
                            rep_tok = int(len(co) * 0.3)
                        for tc in d.get("tool_calls", []):
                            name = tc.get("name")
                            if not name:
                                continue
                            tools.append(name)
                            args = tc.get("args") or {}
                            if name == "run_command":
                                cmd = str(args.get("CommandLine", "")).strip()
                                if cmd:
                                    prog = os.path.basename(cmd.split()[0].replace('"', "").replace("'", ""))
                                    if prog.endswith(".py"):
                                        prog = "python3"
                                    elif prog.endswith(".sh"):
                                        prog = "bash"
                                    if prog:
                                        cmds.append(prog)
                            else:
                                path_arg = str(args.get("Path") or args.get("AbsolutePath") or args.get("TargetFile") or "").replace("\\", "/")
                                sm = re.search(r"/skills/([^/]+)/SKILL\.md$", path_arg)
                                if sm:
                                    skills.append(sm.group(1))
                                elif "skill" in name.lower() or args.get("Role"):
                                    r = args.get("Role") or args.get("TypeName") or name
                                    skills.append(r)
                    elif stype in (
                        "GENERIC", "VIEW_FILE", "RUN_COMMAND", "CODE_ACTION",
                        "GREP_SEARCH", "SEARCH_WEB", "LIST_DIRECTORY", "ERROR_MESSAGE",
                    ):
                        tool_out_tok = int(len(str(d.get("content", ""))) * 0.3)

                    step_txt_tok = user_tok + th_tok + rep_tok + tool_out_tok
                    est_text_tokens += step_txt_tok
                    segment_text_tokens += step_txt_tok

                    step_model = ""
                    if stype == "PLANNER_RESPONSE":
                        direct_m = normalize_model_name(d.get("model"))
                        step_model = direct_m or cur_settings_model
                        if step_model:
                            conv_model_counts[step_model] += 1

                    steps_out.append((
                        conv_id, epoch, day_key, hour_int, stype,
                        in_tok, out_tok, cache_tok,
                        user_tok, th_tok, rep_tok, tool_out_tok,
                        tuple(tools), tuple(cmds), tuple(skills),
                        wait_diff, exec_diff, param_diff,
                        step_model,
                    ))
        except Exception:
            pass

        if first_from_model and steps_out:
            for idx, st_item in enumerate(steps_out):
                if st_item[4] == "PLANNER_RESPONSE":
                    if st_item[18]:
                        break
                    steps_out[idx] = st_item[:18] + (first_from_model,)
                    conv_model_counts[first_from_model] += 1

        sorted_models = sorted(conv_model_counts.items(), key=lambda x: x[1], reverse=True)
        primary_model = sorted_models[0][0] if sorted_models else ""
        models_list = [k for k, _ in sorted_models]

        meta = {
            "turns": max(1, turns) if total_steps > 0 else 0,
            "steps_count": total_steps,
            "first_user_title": first_user_title,
            "last_msg": last_user_msg,
            "first_dt_utc": first_dt.astimezone(timezone.utc) if first_dt else None,
            "last_dt_utc": last_dt_msg.astimezone(timezone.utc) if last_dt_msg else None,
            "has_billing_tokens": has_billing_tokens,
            "total_tokens": sum_in + sum_out + sum_cache,
            "last_ctx_tokens": last_ctx_tokens,
            "exact_cost_cny": round((sum_in * PRICE_INPUT_PER_M + sum_cache * PRICE_CACHE_PER_M + sum_out * PRICE_OUTPUT_PER_M) / 1e6, 2),
            "est_text_tokens": est_text_tokens,
            "est_ctx_tokens": min(segment_text_tokens, 980000),
            "primary_model": primary_model,
            "models": models_list,
        }
        with self._lock:
            self._file_step_cache[fpath] = (sig, steps_out)
            self._file_meta_cache[fpath] = (sig, meta)
        return steps_out

    def _get_transcript_meta_cached(self, cid, local_tz):
        """Return cached overview metadata for a conversation's transcript file."""
        tpath = find_transcript_path(cid)
        if not tpath or not os.path.exists(tpath):
            return None
        self._parse_transcript_steps_cached(tpath, local_tz)
        with self._lock:
            entry = self._file_meta_cache.get(tpath)
            return entry[1] if entry else None

    def _build_usage_series(
        self,
        range_key,
        start_local,
        now_local,
        daily_tokens,
        daily_costs,
        daily_steps,
        daily_sessions,
        hourly_tokens,
        hourly_costs,
        hourly_steps,
        hourly_sessions,
        lang="zh",
    ):
        """Build time-series chart bars suited to today (24h), 7d, 30d, or all (weekly)."""
        if range_key == "today":
            points = []
            for hr in range(24):
                tok = hourly_tokens.get(hr, 0)
                cost = hourly_costs.get(hr, 0.0)
                stp = hourly_steps.get(hr, 0)
                sess_cnt = len(hourly_sessions.get(hr, set()))
                points.append({
                    "date": f"{hr:02d}",
                    "full_date": f"{now_local.strftime('%Y-%m-%d')} {hr:02d}:00-{hr:02d}:59",
                    "tokens": tok,
                    "tokens_formatted": format_tokens(tok),
                    "cost": round(cost, 2),
                    "cost_formatted": f"¥{cost:.2f}",
                    "steps": stp,
                    "steps_formatted": format_tokens(stp),
                    "sessions": sess_cnt,
                    "has_tokens": tok > 0,
                })
            return {"title": tr(lang, "今日各小时用量", "Today Hourly Usage"), "mode": "hourly", "points": points}

        if range_key in ("7d", "30d"):
            num_days = 7 if range_key == "7d" else 30
            title = (
                tr(lang, "近 7 天用量", "Last 7 Days Usage")
                if range_key == "7d"
                else tr(lang, "近 30 天用量", "Last 30 Days Usage")
            )
            points = []
            for i in range(num_days - 1, -1, -1):
                day_dt = now_local - timedelta(days=i)
                day_str = day_dt.strftime("%Y-%m-%d")
                tok = daily_tokens.get(day_str, 0)
                cost = daily_costs.get(day_str, 0.0)
                stp = daily_steps.get(day_str, 0)
                sess_cnt = len(daily_sessions.get(day_str, set()))
                points.append({
                    "date": day_str[5:],
                    "full_date": day_str,
                    "tokens": tok,
                    "tokens_formatted": format_tokens(tok),
                    "cost": round(cost, 2),
                    "cost_formatted": f"¥{cost:.2f}",
                    "steps": stp,
                    "steps_formatted": format_tokens(stp),
                    "sessions": sess_cnt,
                    "has_tokens": tok > 0,
                })
            return {"title": title, "mode": "daily", "points": points}

        all_days = sorted([d for d in daily_steps.keys() if d and len(d) == 10])
        if not all_days:
            return {"title": tr(lang, "全部历史用量趋势", "All-Time Usage Trend"), "mode": "weekly", "points": []}
        first_d = datetime.strptime(all_days[0], "%Y-%m-%d").date()
        last_d = max(datetime.strptime(all_days[-1], "%Y-%m-%d").date(), now_local.date())
        wk_start = first_d - timedelta(days=first_d.weekday())
        buckets = []
        cur = wk_start
        while cur <= last_d:
            buckets.append(cur)
            cur += timedelta(days=7)
        if len(buckets) > 20:
            buckets = buckets[-20:]
        points = []
        for ws in buckets:
            tok = 0
            cost = 0.0
            stp = 0
            sess_set = set()
            for off in range(7):
                dstr = (ws + timedelta(days=off)).strftime("%Y-%m-%d")
                tok += daily_tokens.get(dstr, 0)
                cost += daily_costs.get(dstr, 0.0)
                stp += daily_steps.get(dstr, 0)
                sess_set |= daily_sessions.get(dstr, set())
            sess_cnt = len(sess_set)
            we = min(ws + timedelta(days=6), last_d)
            points.append({
                "date": ws.strftime("%m-%d"),
                "full_date": f"{ws.strftime('%Y-%m-%d')} ~ {we.strftime('%m-%d')}",
                "tokens": tok,
                "tokens_formatted": format_tokens(tok),
                "cost": round(cost, 2),
                "cost_formatted": f"¥{cost:.2f}",
                "steps": stp,
                "steps_formatted": format_tokens(stp),
                "sessions": sess_cnt,
                "has_tokens": tok > 0,
            })
        return {"title": tr(lang, "全部历史用量趋势 (按周)", "All-Time Usage (Weekly)"), "mode": "weekly", "points": points}

    def collect_analytics(self, target_conv_id=None, time_range="all", lang="zh"):
        lang = normalize_lang(lang)
        range_key, start_local, now_local, start_utc, range_label, session_kpi_label = get_time_range_bounds(time_range, lang=lang)
        now_ts = time.time()
        cache_key = (range_key, lang)
        with self._lock:
            cached_entry = self._range_caches.get(cache_key)
            if cached_entry and (now_ts - cached_entry[0] < self.cache_ttl):
                return cached_entry[1]

        conv_rows = fetch_merged_conversations()
        root_rows = []
        child_to_root = {}
        for r in conv_rows:
            cid = r["conversation_id"]
            pid = r.get("parent_conversation_id")
            if pid:
                child_to_root[cid] = pid
            else:
                root_rows.append(r)

        def resolve_root(cid):
            seen = set()
            cur = cid
            while cur in child_to_root and cur not in seen:
                seen.add(cur)
                cur = child_to_root[cur]
            return cur

        local_tz = now_local.tzinfo
        all_transcript_files = []
        seen_cids = set()
        for b_dir in get_brain_dirs():
            if os.path.exists(b_dir):
                for fpath in glob.glob(os.path.join(b_dir, "*", ".system_generated", "logs", "transcript.jsonl")):
                    cid = fpath.split(os.sep)[-4]
                    if cid not in seen_cids:
                        seen_cids.add(cid)
                        all_transcript_files.append(fpath)

        live_set = set(all_transcript_files)
        with self._lock:
            for stale in list(self._file_step_cache.keys()):
                if stale not in live_set:
                    del self._file_step_cache[stale]
                    self._file_meta_cache.pop(stale, None)

        cutoff_epoch = start_local.timestamp() if start_local is not None else None

        total_input_tokens = 0
        total_output_tokens = 0
        total_cache_read_tokens = 0
        total_turns = 0

        tool_counts = defaultdict(int)
        cmd_counts = defaultdict(int)
        skill_counts = defaultdict(int)

        daily_tokens = defaultdict(int)
        daily_costs = defaultdict(float)
        daily_steps = defaultdict(int)
        daily_sessions = defaultdict(set)
        hourly_tokens = defaultdict(int)
        hourly_costs = defaultdict(float)
        hourly_steps = defaultdict(int)
        hourly_sessions = defaultdict(set)

        active_root_cids = set()
        billed_root_cids = set()
        user_tok_sum = 0
        th_tok_sum = 0
        rep_tok_sum = 0
        tool_out_tok_sum = 0

        model_wait_sec = 0.0
        tool_exec_sec = 0.0
        model_thinking_sec = 0.0
        model_reply_sec = 0.0
        tool_param_sec = 0.0
        model_calls_count = 0
        thinking_steps_count = 0
        reply_steps_count = 0
        tool_steps_count = 0

        swarm_model_map = get_swarm_model_map()
        parsed_files = []
        conv_primary_model = {}
        for fpath in all_transcript_files:
            steps = self._parse_transcript_steps_cached(fpath, local_tz)
            parsed_files.append(steps)
            cid_p = fpath.split(os.sep)[-4]
            with self._lock:
                meta_entry = self._file_meta_cache.get(fpath)
            p_mod = meta_entry[1].get("primary_model", "") if (meta_entry and isinstance(meta_entry[1], dict)) else ""
            if not p_mod:
                p_mod = swarm_model_map.get(cid_p, "")
            if p_mod:
                conv_primary_model[cid_p] = p_mod

        model_stats = {}
        unknown_mod_lbl = get_unknown_model_label(lang)

        for steps in parsed_files:
            for st in steps:
                (
                    conv_id, epoch, day_key, hour_int, stype,
                    in_tok, out_tok, cache_tok,
                    user_tok, th_tok, rep_tok, tool_out_tok,
                    tools, cmds, skills,
                    wait_diff, exec_diff, param_diff,
                    step_model,
                ) = st

                root_cid = resolve_root(conv_id)
                step_tokens = in_tok + out_tok + cache_tok
                step_cost = (in_tok * PRICE_INPUT_PER_M + cache_tok * PRICE_CACHE_PER_M + out_tok * PRICE_OUTPUT_PER_M) / 1e6

                daily_tokens[day_key] += step_tokens
                daily_costs[day_key] += step_cost
                daily_steps[day_key] += 1
                daily_sessions[day_key].add(root_cid)

                if cutoff_epoch is not None and epoch < cutoff_epoch:
                    continue

                active_root_cids.add(root_cid)
                if step_tokens > 0:
                    billed_root_cids.add(root_cid)
                total_input_tokens += in_tok
                total_output_tokens += out_tok
                total_cache_read_tokens += cache_tok
                user_tok_sum += user_tok
                th_tok_sum += th_tok
                rep_tok_sum += rep_tok
                tool_out_tok_sum += tool_out_tok
                if th_tok > 0:
                    thinking_steps_count += 1
                if rep_tok > 0:
                    reply_steps_count += 1
                if tools:
                    tool_steps_count += 1

                if range_key == "today":
                    hourly_tokens[hour_int] += step_tokens
                    hourly_costs[hour_int] += step_cost
                    hourly_steps[hour_int] += 1
                    hourly_sessions[hour_int].add(root_cid)

                model_wait_sec += wait_diff
                tool_exec_sec += exec_diff
                tool_param_sec += param_diff
                model_thinking_sec += th_tok / DEFAULT_OUTPUT_SPEED
                model_reply_sec += rep_tok / DEFAULT_OUTPUT_SPEED

                if stype == "USER_INPUT":
                    total_turns += 1
                elif stype == "PLANNER_RESPONSE":
                    model_calls_count += 1
                    eff_model = step_model or swarm_model_map.get(conv_id) or ""
                    if not eff_model and conv_id in child_to_root:
                        eff_model = conv_primary_model.get(child_to_root[conv_id]) or conv_primary_model.get(root_cid) or ""
                    if not eff_model:
                        eff_model = unknown_mod_lbl
                    mst = model_stats.get(eff_model)
                    if mst is None:
                        mst = {
                            "calls": 0,
                            "input_tokens": 0,
                            "cache_read_tokens": 0,
                            "output_tokens": 0,
                            "tokens": 0,
                            "cost": 0.0,
                            "sessions": set(),
                        }
                        model_stats[eff_model] = mst
                    mst["calls"] += 1
                    mst["input_tokens"] += in_tok
                    mst["cache_read_tokens"] += cache_tok
                    mst["output_tokens"] += out_tok
                    mst["tokens"] += step_tokens
                    mst["cost"] += step_cost
                    mst["sessions"].add(root_cid)

                    for tname in tools:
                        tool_counts[tname] += 1
                    for cname in cmds:
                        cmd_counts[cname] += 1
                    for sname in skills:
                        skill_counts[sname] += 1

        matched_roots = []
        for r in root_rows:
            cid = r["conversation_id"]
            if start_utc is None:
                matched_roots.append(r)
            else:
                dt = parse_iso(r.get("last_modified_time"))
                in_db_range = bool(dt and dt.year >= 2000 and dt.astimezone(timezone.utc) >= start_utc)
                if in_db_range or cid in active_root_cids:
                    matched_roots.append(r)

        total_sessions = len(matched_roots) if root_rows else len(active_root_cids)
        archived_sessions = sum(1 for r in matched_roots if r.get("status") == "CASCADE_RUN_STATUS_ARCHIVED")
        matched_cids = {r["conversation_id"] for r in matched_roots} if matched_roots else active_root_cids
        billed_sessions = len(matched_cids & billed_root_cids)

        total_tokens = total_input_tokens + total_output_tokens + total_cache_read_tokens
        total_cost_cny = (total_input_tokens * PRICE_INPUT_PER_M + total_cache_read_tokens * PRICE_CACHE_PER_M + total_output_tokens * PRICE_OUTPUT_PER_M) / 1e6

        denom_in = total_input_tokens + total_cache_read_tokens
        cache_hit_rate = (total_cache_read_tokens / denom_in * 100.0) if denom_in > 0 else 0.0
        total_tool_calls = sum(tool_counts.values())

        total_active_sec = model_wait_sec + model_thinking_sec + model_reply_sec + tool_param_sec + tool_exec_sec

        def dur_pct(sec):
            return round((sec / total_active_sec) * 100.0, 1) if total_active_sec > 0 else 0.0

        gen_sec = model_thinking_sec + model_reply_sec
        output_speed = round((th_tok_sum + rep_tok_sum) / gen_sec) if gen_sec > 1 and (th_tok_sum + rep_tok_sum) > 0 else int(DEFAULT_OUTPUT_SPEED)

        usage_chart = self._build_usage_series(
            range_key, start_local, now_local, daily_tokens, daily_costs, daily_steps, daily_sessions,
            hourly_tokens, hourly_costs, hourly_steps, hourly_sessions, lang=lang,
        )

        token_breakdown = []
        if total_tokens > 0:
            in_text_total = tool_out_tok_sum + user_tok_sum
            in_tool_share = (tool_out_tok_sum / in_text_total) if in_text_total > 0 else 0.85
            in_user_share = 1.0 - in_tool_share

            out_text_total = th_tok_sum + rep_tok_sum
            out_th_share = (th_tok_sum / out_text_total) if out_text_total > 0 else 0.7
            out_rep_share = 1.0 - out_th_share

            raw_slices = [
                (tr(lang, "缓存复用读取", "Cache Read"), float(total_cache_read_tokens), "#10b981", ""),
                (tr(lang, "新增输入与工具上下文", "New Input & Context"), total_input_tokens * in_tool_share, "#3b82f6", "≈"),
                (tr(lang, "用户指令输入", "User Prompts"), total_input_tokens * in_user_share, "#f59e0b", "≈"),
                (tr(lang, "模型思考产出", "Model Thinking"), total_output_tokens * out_th_share, "#8b5cf6", "≈"),
                (tr(lang, "模型回复与调用", "Replies & Calls"), total_output_tokens * out_rep_share, "#06b6d4", "≈"),
            ]
            for label, tok_val, color, prefix in raw_slices:
                pct = round((tok_val / total_tokens) * 100.0, 2) if total_tokens > 0 else 0.0
                token_breakdown.append({
                    "label": label,
                    "pct": pct,
                    "tokens": round(tok_val),
                    "formatted": f"{prefix}{format_tokens(tok_val)}" if tok_val > 0 else "0",
                    "color": color,
                })
        else:
            est_sum = tool_out_tok_sum + th_tok_sum + rep_tok_sum + user_tok_sum
            raw_slices = [
                (tr(lang, "工具输出估算", "Est. Tool Output"), float(tool_out_tok_sum), "#3b82f6", "≈"),
                (tr(lang, "模型思考估算", "Est. Thinking"), float(th_tok_sum), "#8b5cf6", "≈"),
                (tr(lang, "模型回复估算", "Est. Replies"), float(rep_tok_sum), "#06b6d4", "≈"),
                (tr(lang, "用户指令估算", "Est. Prompts"), float(user_tok_sum), "#f59e0b", "≈"),
            ]
            for label, tok_val, color, prefix in raw_slices:
                pct = round((tok_val / est_sum) * 100.0, 2) if est_sum > 0 else 0.0
                token_breakdown.append({
                    "label": label,
                    "pct": pct,
                    "tokens": round(tok_val),
                    "formatted": f"{prefix}{format_tokens(tok_val)}" if tok_val > 0 else "0",
                    "color": color,
                })

        duration_breakdown = [
            {"label": tr(lang, "模型等待", "Model Wait"), "pct": dur_pct(model_wait_sec), "duration": model_wait_sec, "desc": f"{format_duration(model_wait_sec)} · {format_tokens(model_calls_count)} " + tr(lang, "次请求", "reqs"), "color": "#3b82f6"},
            {"label": tr(lang, "模型思考", "Model Thinking"), "pct": dur_pct(model_thinking_sec), "duration": model_thinking_sec, "desc": f"{format_duration(model_thinking_sec)} · {format_tokens(thinking_steps_count)} " + tr(lang, "步思考", "steps"), "color": "#8b5cf6"},
            {"label": tr(lang, "模型回复", "Model Reply"), "pct": dur_pct(model_reply_sec), "duration": model_reply_sec, "desc": f"{format_duration(model_reply_sec)} · {format_tokens(reply_steps_count)} " + tr(lang, "步回复", "steps"), "color": "#ec4899"},
            {"label": tr(lang, "工具参数", "Tool Args"), "pct": dur_pct(tool_param_sec), "duration": tool_param_sec, "desc": f"{format_duration(tool_param_sec)} · {format_tokens(tool_steps_count)} " + tr(lang, "步调用", "calls"), "color": "#f59e0b"},
            {"label": tr(lang, "工具执行", "Tool Exec"), "pct": dur_pct(tool_exec_sec), "duration": tool_exec_sec, "desc": f"{format_duration(tool_exec_sec)} · {format_tokens(total_tool_calls)} " + tr(lang, "次执行", "runs"), "color": "#10b981"},
        ]

        heatmap_days = []
        today_date = now_local.date()
        cur_wk_start = today_date - timedelta(days=today_date.weekday())
        start_day = cur_wk_start - timedelta(weeks=23)
        heatmap_cutoff_day = start_local.strftime("%Y-%m-%d") if start_local else None
        today_str = today_date.strftime("%Y-%m-%d")
        month_names = []
        for i in range(168):
            cur = start_day + timedelta(days=i)
            cur_str = cur.strftime("%Y-%m-%d")
            m_lbl = format_month_label(cur.month, lang)
            if m_lbl not in month_names:
                month_names.append(m_lbl)
            d_tok = daily_tokens.get(cur_str, 0)
            d_sess = len(daily_sessions.get(cur_str, set()))
            d_steps = daily_steps.get(cur_str, 0)
            heatmap_days.append({
                "date": cur_str,
                "tokens": d_tok,
                "tokens_formatted": format_tokens(d_tok),
                "sessions": d_sess,
                "steps": d_steps,
                "weekday": cur.weekday(),
                "future": cur_str > today_str,
                "in_range": True if not heatmap_cutoff_day else (cur_str >= heatmap_cutoff_day),
            })

        top_skills = sorted(skill_counts.items(), key=lambda x: x[1], reverse=True)[:8]
        top_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        top_commands = sorted(cmd_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        total_model_tokens = sum(v["tokens"] for v in model_stats.values())
        total_model_calls = sum(v["calls"] for v in model_stats.values())
        sorted_model_stats = sorted(
            model_stats.items(),
            key=lambda kv: (kv[1]["tokens"], kv[1]["calls"], kv[0]),
            reverse=True,
        )
        model_items = []
        family_agg = {}
        palette_idx = 0
        for mname, st in sorted_model_stats:
            is_unk = (mname == unknown_mod_lbl)
            if is_unk:
                color = FAMILY_COLORS["Unrecorded" if lang == "en" else "未记录"]
            else:
                color = MODEL_PALETTE[palette_idx % len(MODEL_PALETTE)]
                palette_idx += 1
            fam = get_model_family(mname, lang=lang)
            m_toks = st["tokens"]
            m_calls = st["calls"]
            m_in = st["input_tokens"]
            m_ca = st["cache_read_tokens"]
            m_out = st["output_tokens"]
            m_denom = m_in + m_ca
            m_cache_rate = round((m_ca / m_denom) * 100.0, 1) if m_denom > 0 else 0.0
            tok_pct = round((m_toks / total_model_tokens) * 100.0, 2) if total_model_tokens > 0 else 0.0
            calls_pct = round((m_calls / total_model_calls) * 100.0, 2) if total_model_calls > 0 else 0.0
            model_items.append({
                "name": mname,
                "family": fam,
                "color": color,
                "is_unknown": is_unk,
                "calls": m_calls,
                "calls_formatted": format_tokens(m_calls),
                "calls_pct": calls_pct,
                "tokens": m_toks,
                "tokens_formatted": format_tokens(m_toks),
                "tokens_pct": tok_pct,
                "input_tokens": m_in,
                "input_formatted": format_tokens(m_in),
                "cache_read_tokens": m_ca,
                "cache_formatted": format_tokens(m_ca),
                "output_tokens": m_out,
                "output_formatted": format_tokens(m_out),
                "cache_hit_rate": m_cache_rate,
                "cost": round(st["cost"], 2),
                "cost_formatted": f"¥{st['cost']:.2f}",
                "sessions": len(st["sessions"]),
                "has_tokens": m_toks > 0,
            })
            fa = family_agg.get(fam)
            if fa is None:
                fa = {"calls": 0, "tokens": 0}
                family_agg[fam] = fa
            fa["calls"] += m_calls
            fa["tokens"] += m_toks

        model_families = []
        for fam, fv in sorted(family_agg.items(), key=lambda kv: (kv[1]["tokens"], kv[1]["calls"], kv[0]), reverse=True):
            model_families.append({
                "family": fam,
                "color": FAMILY_COLORS.get(fam, "#64748b"),
                "calls": fv["calls"],
                "calls_pct": round((fv["calls"] / total_model_calls) * 100.0, 1) if total_model_calls > 0 else 0.0,
                "tokens": fv["tokens"],
                "tokens_formatted": format_tokens(fv["tokens"]),
                "tokens_pct": round((fv["tokens"] / total_model_tokens) * 100.0, 1) if total_model_tokens > 0 else 0.0,
            })

        model_usage = {
            "total_models": len(model_items),
            "total_calls": total_model_calls,
            "total_tokens": total_model_tokens,
            "has_billing_tokens": total_model_tokens > 0,
            "range_label": range_label,
            "items": model_items,
            "families": model_families,
        }

        top_mod_sig = f"{model_items[0]['name']}:{model_items[0]['calls']}" if model_items else "none"
        ana_sig = f"{lang}:{range_key}:{total_sessions}:{archived_sessions}:{total_tokens}:{total_turns}:{total_tool_calls}:{int(total_active_sec)}:{len(model_items)}:{top_mod_sig}"
        result = {
            "lang": lang,
            "sig": ana_sig,
            "time_range": range_key,
            "range_label": range_label,
            "kpi": {
                "session_label": session_kpi_label,
                "total_sessions": total_sessions,
                "archived_sessions": archived_sessions,
                "total_tokens": total_tokens,
                "total_tokens_formatted": format_tokens(total_tokens),
                "total_turns": total_turns,
                "estimated_cost": round(total_cost_cny, 2),
                "priced_sessions": f"{billed_sessions}/{total_sessions}",
                "cache_hit_rate": round(cache_hit_rate, 2),
                "cache_sessions": billed_sessions,
                "tool_calls": total_tool_calls,
                "tool_calls_formatted": format_tokens(total_tool_calls),
                "tool_exec_duration": format_duration(tool_exec_sec),
                "active_duration": format_duration(total_active_sec),
                "model_calls": format_tokens(model_calls_count),
                "output_speed": output_speed,
            },
            "usage_chart": usage_chart,
            "token_breakdown": token_breakdown,
            "duration_breakdown": duration_breakdown,
            "model_usage": model_usage,
            "heatmap": heatmap_days,
            "heatmap_months_label": " · ".join(month_names),
            "top_skills": [{"name": k, "count": v, "formatted": f"x{v}"} for k, v in top_skills],
            "top_tools": [{"name": k, "count": v, "formatted": f"x{format_tokens(v)}"} for k, v in top_tools],
            "top_commands": [{"name": k, "count": v, "formatted": f"x{format_tokens(v)}"} for k, v in top_commands],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        with self._lock:
            self._range_caches[cache_key] = (now_ts, result)
        return result

    def collect_sessions_overview(self, current_cid=None, limit=None, time_range="all", lang="zh"):
        lang = normalize_lang(lang)
        range_key, _, now_local, start_utc, range_label, _ = get_time_range_bounds(time_range, lang=lang)
        now_ts = time.time()
        cache_key = (range_key, current_cid, limit, lang)
        with self._lock:
            cached_sess = self._sessions_caches.get(cache_key)
            if cached_sess and (now_ts - cached_sess[0] < self.cache_ttl):
                return cached_sess[1]

        all_rows = fetch_merged_conversations(limit=None)
        root_rows = [r for r in all_rows if not r.get("parent_conversation_id")]
        known_cids = {r["conversation_id"] for r in all_rows}
        for b_dir in get_brain_dirs():
            if not os.path.exists(b_dir):
                continue
            for fpath in glob.glob(os.path.join(b_dir, "*", ".system_generated", "logs", "transcript.jsonl")):
                cid = fpath.split(os.sep)[-4]
                if cid not in known_cids:
                    known_cids.add(cid)
                    root_rows.append({
                        "conversation_id": cid,
                        "title": "",
                        "status": "CASCADE_RUN_STATUS_IDLE",
                        "not_fully_idle": 0,
                        "step_count": 0,
                        "last_modified_time": "",
                        "workspace_uris": "",
                        "parent_conversation_id": "",
                    })

        if not root_rows:
            return {
                "lang": lang,
                "time_range": range_key,
                "range_label": range_label,
                "sessions": [],
                "workspaces": [{"name": tr(lang, "全部", "All"), "key": "all", "count": 0}],
                "months": [{"key": "all", "label": tr(lang, "全部月份", "All Months"), "count": 0}],
                "total_count": 0,
            }

        def get_rel_time(dt):
            if not dt or dt.year < 2000:
                return format_relative_time(None, lang)
            now = datetime.now(timezone.utc)
            return format_relative_time((now - dt).total_seconds(), lang)

        swarm_model_map = get_swarm_model_map()
        unknown_mod_lbl = get_unknown_model_label(lang)
        local_tz = now_local.tzinfo
        sessions = []
        ws_counts = {}
        month_counts = {}

        for r in root_rows:
            cid = r["conversation_id"]
            status = r.get("status")
            is_running = (status == "CASCADE_RUN_STATUS_RUNNING" or r.get("not_fully_idle") == 1)
            is_current = bool(current_cid and cid == current_cid)

            meta = self._get_transcript_meta_cached(cid, local_tz)
            dt = resolve_conversation_dt(cid, r.get("last_modified_time"), local_tz, self)

            if start_utc is not None:
                in_win = bool(dt and dt.year >= 2000 and dt.astimezone(timezone.utc) >= start_utc)
                if not (in_win or is_running or is_current):
                    continue

            db_title = (r.get("title") or "").strip()
            meta_title = (meta.get("first_user_title") or "").strip() if meta else ""
            title = db_title or meta_title or tr(lang, f"未命名任务 ({cid[:8]})", f"Untitled Task ({cid[:8]})")

            steps = max(r.get("step_count") or 0, meta.get("steps_count", 0) if meta else 0)
            turns = meta.get("turns", 1) if (meta and meta.get("turns", 0) > 0) else max(1, steps and 1)

            ws_name = extract_workspace_name(r.get("workspace_uris"))
            ws_counts[ws_name] = ws_counts.get(ws_name, 0) + 1

            rel_time = get_rel_time(dt)
            if dt and dt.year >= 2000:
                local_dt = dt.astimezone(local_tz)
                created_day = local_dt.strftime("%Y-%m-%d")
                created_month = local_dt.strftime("%Y-%m")
                sort_ts = dt.timestamp()
            else:
                created_day = "-"
                created_month = "unknown"
                sort_ts = 0.0
            month_counts[created_month] = month_counts.get(created_month, 0) + 1

            has_billing = bool(meta and meta.get("has_billing_tokens"))
            if has_billing:
                total_tokens = meta["total_tokens"]
                ctx_tokens = meta["last_ctx_tokens"] if meta["last_ctx_tokens"] > 0 else meta["est_ctx_tokens"]
                occupancy_pct = min(round((ctx_tokens / CONTEXT_WINDOW_TOKENS) * 100, 1), 100.0)
                cost_cny = f"{meta['exact_cost_cny']:.2f}"
                est_text = 0
            else:
                est_text = meta["est_text_tokens"] if meta else 0
                est_ctx = meta["est_ctx_tokens"] if meta else 0
                total_tokens = 0
                ctx_tokens = est_ctx
                occupancy_pct = min(round((est_ctx / CONTEXT_WINDOW_TOKENS) * 100, 1), 100.0) if est_ctx > 0 else 0.0
                cost_cny = "--"

            last_msg = ((meta.get("last_msg") or "").strip()[:64]) if meta else ""

            s_models = list(meta.get("models") or []) if meta else []
            sw_mod = swarm_model_map.get(cid)
            if sw_mod and sw_mod not in s_models:
                s_models.append(sw_mod)
            primary_model = s_models[0] if s_models else ""
            if not s_models and steps > 0:
                s_models = [unknown_mod_lbl]

            item = {
                "id": cid,
                "title": title,
                "workspace": ws_name,
                "primary_model": primary_model,
                "models": s_models,
                "running": is_running,
                "current": is_current,
                "archived": (status == "CASCADE_RUN_STATUS_ARCHIVED"),
                "steps": steps,
                "turns": turns,
                "has_billing_tokens": has_billing,
                "context_tokens": ctx_tokens,
                "occupancy_pct": occupancy_pct,
                "total_tokens": total_tokens,
                "cost_cny": cost_cny,
                "last_msg": last_msg or tr(lang, "会话执行完成", "Session completed"),
                "relative_time": rel_time,
                "created_day": created_day,
                "_sort_ts": sort_ts,
            }
            if not has_billing and est_text > 0:
                item["est_tokens"] = est_text
            sessions.append(item)

        sessions.sort(key=lambda s: s["_sort_ts"], reverse=True)
        if limit is not None:
            sessions = sessions[:limit]
        for s in sessions:
            s.pop("_sort_ts", None)

        chips = [{"name": tr(lang, "全部", "All"), "key": "all", "count": len(sessions)}]
        for k, v in sorted(ws_counts.items(), key=lambda x: x[1], reverse=True):
            chips.append({"name": k, "key": k, "count": v})

        month_opts = [{"key": "all", "label": tr(lang, f"全部月份 ({len(sessions)})", f"All Months ({len(sessions)})"), "count": len(sessions)}]
        for mk in sorted([k for k in month_counts.keys() if k != "unknown"], reverse=True):
            month_opts.append({"key": mk, "label": f"{mk} ({month_counts[mk]})", "count": month_counts[mk]})
        if "unknown" in month_counts:
            month_opts.append({
                "key": "unknown",
                "label": tr(lang, f"日期未知 ({month_counts['unknown']})", f"Unknown Date ({month_counts['unknown']})"),
                "count": month_counts["unknown"],
            })

        top_sig = f"{sessions[0]['id']}:{sessions[0]['steps']}:{sessions[0]['running']}" if sessions else "empty"
        sum_steps = sum(s.get("steps", 0) for s in sessions)
        sum_toks = sum(s.get("total_tokens", 0) for s in sessions)
        sess_sig = f"{lang}:{range_key}:{len(sessions)}:{sum_steps}:{sum_toks}:{top_sig}"
        out = {
            "lang": lang,
            "sig": sess_sig,
            "time_range": range_key,
            "range_label": range_label,
            "sessions": sessions,
            "workspaces": chips,
            "months": month_opts,
            "total_count": len(sessions),
        }
        with self._lock:
            self._sessions_caches[cache_key] = (now_ts, out)
        return out

    def analyze_context_timeline(self, cid, lang="zh"):
        return _analyze_timeline(cid, self._timeline_cache, self._lock, lang=lang)
