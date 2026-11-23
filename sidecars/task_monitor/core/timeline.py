"""Session context evolution timeline and diagnostic analyzer."""

import json
import os
import time

from core.config import CONTEXT_WINDOW_TOKENS
from core.formatting import clean_user_prompt, format_tokens, stat_sig
from core.i18n import normalize_lang, tr
from core.storage import find_transcript_path

_TOOL_OUTPUT_TYPES = (
    "GENERIC", "VIEW_FILE", "RUN_COMMAND", "CODE_ACTION",
    "GREP_SEARCH", "SEARCH_WEB", "LIST_DIRECTORY", "ERROR_MESSAGE",
)


def analyze_context_timeline(cid, timeline_cache, lock, lang="zh"):
    """Build per-turn context trajectory, spike/compaction events, and optimization hints."""
    lang = normalize_lang(lang)
    if not cid:
        return {"error": tr(lang, "缺少会话 ID", "Missing conversation id"), "turns": [], "recommendations": []}

    t0 = time.time()
    tpath = find_transcript_path(cid)
    if not tpath or not os.path.exists(tpath):
        return {"error": tr(lang, "未找到会话日志", "Transcript not found"), "turns": [], "recommendations": []}

    cache_key = (cid, lang)
    sig = stat_sig(tpath)
    if sig is not None:
        with lock:
            cached = timeline_cache.get(cache_key)
            if cached and cached[0] == sig:
                return cached[1]

    steps = []
    try:
        with open(tpath, "rb") as f:
            for line in f:
                if line.strip():
                    try:
                        steps.append(json.loads(line.decode("utf-8", errors="ignore")))
                    except Exception:
                        pass
    except Exception as e:
        return {"error": str(e), "turns": [], "recommendations": []}

    turns = []
    current_turn = None
    repeated_files = {}
    large_tools = []
    compaction_events = []

    for s in steps:
        stype = s.get("type")
        sindex = s.get("step_index", len(steps))

        for tc in s.get("tool_calls", []):
            tname = tc.get("name")
            args = tc.get("args") or {}
            if tname in ("read_file", "view_file"):
                fpath = args.get("Path") or args.get("AbsolutePath") or args.get("TargetFile") or ""
                if fpath:
                    repeated_files[fpath] = repeated_files.get(fpath, 0) + 1

        step_est = 0
        if stype in _TOOL_OUTPUT_TYPES:
            content_str = str(s.get("content", ""))
            step_est = int(len(content_str) * 0.3)
            if len(content_str) > 12000:
                approx_tokens = len(content_str) // 4
                large_tools.append({
                    "step_index": sindex,
                    "tokens": approx_tokens,
                    "preview": content_str[:120].replace(chr(10), " "),
                })
        elif stype == "PLANNER_RESPONSE":
            th = str(s.get("thinking") or "")
            co = str(s.get("content") or "")
            tc_len = sum(len(str(tc.get("args") or "")) for tc in (s.get("tool_calls") or []))
            step_est = int((len(th) + len(co) + tc_len) * 0.3)

        if stype == "USER_INPUT":
            if current_turn:
                turns.append(current_turn)
            raw_u = str(s.get("content", ""))
            u_est = int(len(raw_u) * 0.3)
            current_turn = {
                "turn_index": len(turns) + 1,
                "user_prompt": clean_user_prompt(raw_u, max_len=110),
                "created_at": s.get("created_at"),
                "step_start": sindex,
                "step_end": sindex,
                "context_tokens": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "tools": [],
                "has_compaction": "<CONTEXT_SUMMARY>" in raw_u,
                "compaction_delta": 0,
                "is_spike": False,
                "_est_tokens": u_est,
            }
        else:
            if not current_turn:
                current_turn = {
                    "turn_index": 1,
                    "user_prompt": tr(lang, "初始指令", "Initial prompt"),
                    "created_at": s.get("created_at"),
                    "step_start": sindex,
                    "step_end": sindex,
                    "context_tokens": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_read_tokens": 0,
                    "tools": [],
                    "has_compaction": False,
                    "compaction_delta": 0,
                    "is_spike": False,
                    "_est_tokens": 0,
                }
            current_turn["step_end"] = sindex
            current_turn["_est_tokens"] += step_est
            inp = s.get("input_tokens", 0) or 0
            out = s.get("output_tokens", 0) or 0
            cache = s.get("cache_read_tokens", 0) or 0
            if inp > 0:
                current_turn["input_tokens"] = inp
                current_turn["cache_read_tokens"] = cache
                current_turn["context_tokens"] = inp + cache
            current_turn["output_tokens"] += out

            for tc in s.get("tool_calls", []):
                tname = tc.get("name")
                if tname and tname not in current_turn["tools"]:
                    current_turn["tools"].append(tname)

    if current_turn:
        turns.append(current_turn)

    prev_ctx = 0
    for t in turns:
        est_inc = max(t.pop("_est_tokens", 0), 120)
        ctx = t["context_tokens"]
        if ctx == 0:
            ctx = est_inc if t["has_compaction"] else (prev_ctx + est_inc)
            t["context_tokens"] = ctx

        delta = ctx - prev_ctx if prev_ctx > 0 else ctx
        t["delta"] = delta
        if prev_ctx > 0 and delta < -10000:
            t["has_compaction"] = True
            t["compaction_delta"] = abs(delta)
            saved_pct = round(abs(delta) / prev_ctx * 100, 1)
            compaction_events.append({
                "turn": t["turn_index"],
                "step": t["step_start"],
                "saved_tokens": abs(delta),
                "saved_pct": saved_pct,
            })
        elif delta > 25000:
            t["is_spike"] = True

        prev_ctx = ctx

    final_ctx = turns[-1]["context_tokens"] if turns else 0
    occupancy_pct = round((final_ctx / CONTEXT_WINDOW_TOKENS) * 100, 1)

    excess_reads = [{"file": k, "count": v} for k, v in repeated_files.items() if v >= 3]
    excess_reads.sort(key=lambda x: x["count"], reverse=True)

    recoms = []
    if occupancy_pct > 65:
        recoms.append({
            "type": "danger",
            "title": tr(lang, "上下文窗口高度饱和 (>65%)", "Context Window Highly Saturated (>65%)"),
            "desc": tr(
                lang,
                f"当前上下文已占用 {final_ctx:,} Tokens（{occupancy_pct}%），模型推理延迟与成本会显著增加。建议输入 /compact 触发裁剪压缩。",
                f"Context currently uses {final_ctx:,} tokens ({occupancy_pct}%), significantly increasing latency and cost. Consider running /compact.",
            ),
            "action": "suggest_compact",
        })
    elif occupancy_pct > 35:
        recoms.append({
            "type": "warning",
            "title": tr(lang, "上下文用量偏高 (>35%)", "Elevated Context Usage (>35%)"),
            "desc": tr(
                lang,
                f"当前上下文已达 {occupancy_pct}%。若后续还需进行复杂排查，可适时执行 /compact 归档早期探索记录。",
                f"Context usage reached {occupancy_pct}%. Run /compact before deep follow-up debugging to archive earlier exploration turns.",
            ),
            "action": "suggest_compact",
        })

    if large_tools:
        top_lt = sorted(large_tools, key=lambda x: x["tokens"], reverse=True)[:3]
        recoms.append({
            "type": "warning",
            "title": tr(lang, f"检测到 {len(large_tools)} 次超大工具输出", f"Detected {len(large_tools)} Oversized Tool Outputs"),
            "desc": tr(
                lang,
                f"最大单步工具输出产生约 {top_lt[0]['tokens']:,} Tokens。建议针对 grep、cat、find 等命令增加 head -n 截断或定向过滤，避免海量日志倾倒进上下文。",
                f"Largest single tool output added ~{top_lt[0]['tokens']:,} tokens. Add targeted filters or head truncation for grep/cat/find outputs.",
            ),
            "action": "check_tool_spikes",
            "items": top_lt,
        })

    if excess_reads:
        top_r = excess_reads[:3]
        fname = os.path.basename(top_r[0]["file"])
        recoms.append({
            "type": "info",
            "title": tr(lang, "检测到重复全量读取文件", "Repeated Full File Reads Detected"),
            "desc": tr(
                lang,
                f"如 {fname} 被重复完整读取 {top_r[0]['count']} 次。建议优先使用精确局部编辑工具，减少重复全量投喂。",
                f"{fname} was read {top_r[0]['count']} times. Prefer bounded line ranges or targeted edits to avoid redundant context growth.",
            ),
            "action": "check_repeated_reads",
            "items": top_r,
        })

    if compaction_events:
        total_saved = sum(e["saved_tokens"] for e in compaction_events)
        recoms.append({
            "type": "success",
            "title": tr(lang, f"历史共完成 {len(compaction_events)} 次有效上下文压缩", f"Completed {len(compaction_events)} Context Compactions"),
            "desc": tr(
                lang,
                f"累计削减上下文约 {total_saved:,} Tokens，会话记忆已被高效提纯并保留关键上下文摘要。",
                f"Reclaimed ~{total_saved:,} tokens across compactions while retaining distilled session summaries.",
            ),
            "action": "compaction_history",
        })

    elapsed_ms = round((time.time() - t0) * 1000, 1)
    out = {
        "lang": lang,
        "conversation_id": cid,
        "turns_count": len(turns),
        "total_steps": len(steps),
        "current_context_tokens": final_ctx,
        "current_context_formatted": format_tokens(final_ctx),
        "occupancy_pct": occupancy_pct,
        "turns": turns,
        "large_tools": large_tools[:5],
        "repeated_reads": excess_reads[:5],
        "compaction_events": compaction_events,
        "recommendations": recoms,
        "elapsed_ms": elapsed_ms,
    }
    if sig is not None:
        with lock:
            timeline_cache[cache_key] = (sig, out)
    return out
