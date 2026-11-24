"""Host-injected Language Server ConnectRPC quota client with TTL cache and safe loopback checks."""

import hashlib
import http.client
import json
import os
import ssl
import threading
import time
import urllib.parse
from datetime import datetime, timezone

from core.formatting import parse_iso
from core.i18n import normalize_lang, tr

QUOTA_CACHE_LOCK = threading.RLock()
QUOTA_CACHE = {
    "sig": None,
    "ts": 0.0,
    "raw": None,
}

DEFAULT_QUOTA_TTL = 15.0
RPC_TIMEOUT_SEC = 2.5
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def _get_quota_ttl():
    raw = os.environ.get("ANTIGRAVITY_QUOTA_TTL", "").strip()
    if raw:
        try:
            val = float(raw)
            if val >= 1.0:
                return val
        except ValueError:
            pass
    return DEFAULT_QUOTA_TTL


def parse_ls_endpoint():
    """Parse ANTIGRAVITY_LS_ADDRESS & ANTIGRAVITY_CSRF_TOKEN strictly for loopback endpoints."""
    raw_addr = (os.environ.get("ANTIGRAVITY_LS_ADDRESS") or "").strip()
    csrf_token = (os.environ.get("ANTIGRAVITY_CSRF_TOKEN") or "").strip()
    if not raw_addr:
        return None

    addr = raw_addr
    has_scheme = "://" in addr
    if not has_scheme:
        if addr.startswith(":"):
            addr = f"http://127.0.0.1{addr}"
        else:
            addr = f"http://{addr}"

    try:
        parsed = urllib.parse.urlparse(addr)
    except Exception:
        return None

    host = (parsed.hostname or "").strip().lower()
    if host not in _LOOPBACK_HOSTS:
        return None

    port = parsed.port
    if not port or port <= 0 or port > 65535:
        return None

    preferred_scheme = "https" if (has_scheme and parsed.scheme.lower() == "https") else "http"
    schemes = (preferred_scheme, "http" if preferred_scheme == "https" else "https")
    return {
        "host": "127.0.0.1" if host == "localhost" else host,
        "port": port,
        "schemes": schemes,
        "csrf": csrf_token,
        "raw_addr": raw_addr,
    }


def _post_connect_rpc(host, port, scheme, csrf, method_path, locale="en"):
    """Send a single ConnectRPC JSON POST request to the local Language Server."""
    payload = json.dumps({
        "metadata": {
            "ideName": "antigravity",
            "extensionName": "antigravity",
            "locale": locale,
        }
    }).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Connect-Protocol-Version": "1",
        "Content-Length": str(len(payload)),
    }
    if csrf:
        headers["x-codeium-csrf-token"] = csrf

    conn = None
    try:
        if scheme == "https":
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            conn = http.client.HTTPSConnection(host, port, timeout=RPC_TIMEOUT_SEC, context=ctx)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=RPC_TIMEOUT_SEC)
        conn.request("POST", method_path, body=payload, headers=headers)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="replace")
        return resp.status, body, None
    except Exception as exc:
        return 0, "", str(exc)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _call_ls_rpc(endpoint, method_path, locale="en", preferred_scheme=None):
    """Try preferred scheme then fallback scheme on loopback endpoint."""
    schemes = endpoint["schemes"]
    if preferred_scheme and preferred_scheme in schemes:
        schemes = (preferred_scheme,) + tuple(s for s in schemes if s != preferred_scheme)

    last_err = ""
    last_status = 0
    for scheme in schemes:
        status, body, err = _post_connect_rpc(
            endpoint["host"],
            endpoint["port"],
            scheme,
            endpoint["csrf"],
            method_path,
            locale=locale,
        )
        if status == 200:
            try:
                return True, scheme, json.loads(body), ""
            except Exception as exc:
                return False, scheme, None, f"Invalid JSON response: {exc}"
        last_status = status
        last_err = err or f"HTTP {status}"
    return False, None, None, last_err or f"HTTP {last_status}"


def _format_reset_countdown(iso_str, lang="zh"):
    """Format resetTime ISO string into localized countdown ('4h 2m' or '4小时 2分钟')."""
    if not iso_str:
        return ""
    dt = parse_iso(iso_str)
    if not dt:
        return ""
    now = datetime.now(timezone.utc)
    diff_sec = (dt.astimezone(timezone.utc) - now).total_seconds()
    if diff_sec <= 0:
        return tr(lang, "即将重置", "Resetting now")

    total_mins = int(diff_sec // 60)
    days = total_mins // (60 * 24)
    hours = (total_mins % (60 * 24)) // 60
    mins = total_mins % 60

    if lang == "en":
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0 or days > 0:
            parts.append(f"{hours}h")
        parts.append(f"{mins}m")
        return " ".join(parts)

    parts = []
    if days > 0:
        parts.append(f"{days}天")
    if hours > 0 or days > 0:
        parts.append(f"{hours}小时")
    parts.append(f"{mins}分钟")
    return " ".join(parts)


def _format_pct_parts(remaining_fraction, disabled=False):
    """Compute numeric percentage, display string, and color level."""
    if disabled:
        return None, "--", "disabled"
    if remaining_fraction is None:
        return None, "N/A", "muted"
    try:
        pct = max(0.0, min(100.0, float(remaining_fraction) * 100.0))
    except (TypeError, ValueError):
        return None, "N/A", "muted"

    if abs(pct - round(pct)) < 0.05:
        pct_text = f"{int(round(pct))}%"
    else:
        pct_text = f"{pct:.1f}%"

    if pct >= 40.0:
        level = "ok"
    elif pct >= 15.0:
        level = "warn"
    else:
        level = "crit"
    return round(pct, 1), pct_text, level


def _localize_bucket_label(bucket, lang="zh"):
    """Normalize bucket window/displayName into localized label."""
    disp = str(bucket.get("displayName") or "").strip()
    win = str(bucket.get("window") or "").strip().lower()
    bid = str(bucket.get("bucketId") or "").strip().lower()
    combined = f"{disp} {win} {bid}".lower()

    if "weekly" in combined or "7d" in combined or "7_day" in combined or "week" in combined:
        return tr(lang, "每周限额", "Weekly limit")
    if "5h" in combined or "5_hour" in combined or "five_hour" in combined or "5-hour" in combined:
        return tr(lang, "5 小时限额", "5h limit")
    return disp or str(bucket.get("window") or bucket.get("bucketId") or tr(lang, "配额窗口", "Quota window"))


def _format_tier_label(user_status_raw):
    """Extract clean plan tier string without exposing account email or PII."""
    if not isinstance(user_status_raw, dict):
        return ""
    tier = str(user_status_raw.get("userTier") or "").strip()
    plan_status = user_status_raw.get("planStatus")
    if isinstance(plan_status, dict):
        plan_info = plan_status.get("planInfo")
        if isinstance(plan_info, dict):
            pname = str(plan_info.get("planName") or plan_info.get("displayName") or "").strip()
            if pname:
                return pname
        p_tier = str(plan_status.get("planName") or plan_status.get("tier") or "").strip()
        if p_tier:
            return p_tier
    if not tier or tier.upper() == "UNKNOWN":
        return ""
    cleaned = tier.replace("TEAMS_TIER_", "").replace("USER_TIER_", "").replace("_", " ").strip()
    return cleaned.title() if cleaned else ""


def _fetch_raw_quota_snapshot(endpoint):
    """Fetch language-agnostic raw quota snapshot from local Language Server."""
    ok, active_scheme, summary_data, err = _call_ls_rpc(
        endpoint,
        "/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary",
        locale="en",
    )
    if not ok:
        return {
            "ok": False,
            "error": err or "RPC failed",
            "summary": None,
            "models": None,
            "user_status": None,
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    ok_models, _, models_data, _ = _call_ls_rpc(
        endpoint,
        "/exa.language_server_pb.LanguageServerService/GetCascadeModelConfigData",
        locale="en",
        preferred_scheme=active_scheme,
    )
    ok_status, _, status_data, _ = _call_ls_rpc(
        endpoint,
        "/exa.language_server_pb.LanguageServerService/GetUserStatus",
        locale="en",
        preferred_scheme=active_scheme,
    )

    return {
        "ok": True,
        "error": "",
        "summary": summary_data,
        "models": models_data if ok_models else None,
        "user_status": status_data if ok_status else None,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _build_quota_response(raw_snap, status_code, lang="zh", cached=False):
    """Transform language-agnostic snapshot into localized API response."""
    if status_code == "unconfigured":
        payload = {
            "lang": lang,
            "available": False,
            "status": "unconfigured",
            "source": "none",
            "status_label": tr(lang, "未注入宿主凭据", "Host Env Not Provided"),
            "message": tr(
                lang,
                "当前 Sidecar 进程未收到宿主注入的 ANTIGRAVITY_LS_ADDRESS 环境变量（仅在宿主主动注入时连接本地 Language Server，不扫描系统进程）。",
                "Host did not inject ANTIGRAVITY_LS_ADDRESS into this sidecar (connects only via host-injected env vars without process scanning).",
            ),
            "hint": tr(
                lang,
                "请在 Antigravity 桌面端「Model → View Usage」或 CLI 中输入 /usage、/credits 查看真实云端额度。",
                "Check live cloud quota in Antigravity App (Model -> View Usage) or CLI (/usage, /credits).",
            ),
            "plan_tier": "",
            "groups": [],
            "models": [],
            "fetched_at": "",
            "cached": False,
        }
    elif not raw_snap or not raw_snap.get("ok"):
        err_msg = (raw_snap or {}).get("error") or tr(lang, "连接失败", "Connection failed")
        payload = {
            "lang": lang,
            "available": False,
            "status": "unreachable",
            "source": "ls_env",
            "status_label": tr(lang, "Language Server 不可达", "LS Unreachable"),
            "message": tr(
                lang,
                f"已检测到宿主注入地址，但调用本地配额接口失败：{err_msg}",
                f"Host endpoint detected, but local quota RPC failed: {err_msg}",
            ),
            "hint": tr(
                lang,
                "可点击右侧刷新重试，或在 Antigravity 桌面端「Model → View Usage」/ CLI `/usage` 查看。",
                "Click Refresh to retry, or view quota in App (Model -> View Usage) / CLI `/usage`.",
            ),
            "plan_tier": "",
            "groups": [],
            "models": [],
            "fetched_at": (raw_snap or {}).get("fetched_at", ""),
            "cached": cached,
        }
    else:
        summary = raw_snap.get("summary") or {}
        raw_groups = (summary.get("response") or {}).get("groups") or []
        groups_out = []
        for g in raw_groups:
            if not isinstance(g, dict):
                continue
            buckets_out = []
            for b in g.get("buckets") or []:
                if not isinstance(b, dict):
                    continue
                disabled = bool(b.get("disabled"))
                pct_val, pct_text, level = _format_pct_parts(b.get("remainingFraction"), disabled=disabled)
                reset_time = str(b.get("resetTime") or "")
                buckets_out.append({
                    "id": str(b.get("bucketId") or ""),
                    "label": _localize_bucket_label(b, lang=lang),
                    "window": str(b.get("window") or ""),
                    "remaining_pct": pct_val,
                    "remaining_text": pct_text,
                    "level": level,
                    "reset_time": reset_time,
                    "resets_in": _format_reset_countdown(reset_time, lang=lang),
                    "disabled": disabled,
                })
            groups_out.append({
                "name": str(g.get("displayName") or tr(lang, "模型配额组", "Model Group")),
                "description": str(g.get("description") or ""),
                "buckets": buckets_out,
            })

        models_out = []
        models_raw = (raw_snap.get("models") or {}).get("clientModelConfigs") or []
        for m in models_raw:
            if not isinstance(m, dict):
                continue
            qi = m.get("quotaInfo")
            if not isinstance(qi, dict):
                continue
            pct_val, pct_text, level = _format_pct_parts(qi.get("remainingFraction"), disabled=False)
            reset_time = str(qi.get("resetTime") or "")
            models_out.append({
                "model_id": str(m.get("modelId") or ""),
                "label": str(m.get("label") or m.get("modelId") or ""),
                "tag": str(m.get("tagTitle") or ""),
                "is_recommended": bool(m.get("isRecommended")),
                "remaining_pct": pct_val,
                "remaining_text": pct_text,
                "level": level,
                "reset_time": reset_time,
                "resets_in": _format_reset_countdown(reset_time, lang=lang),
            })

        plan_tier = _format_tier_label(raw_snap.get("user_status"))
        payload = {
            "lang": lang,
            "available": True,
            "status": "ok",
            "source": "ls_env",
            "status_label": tr(lang, "实时同步", "Live"),
            "message": "",
            "hint": "",
            "plan_tier": plan_tier,
            "groups": groups_out,
            "models": models_out,
            "fetched_at": raw_snap.get("fetched_at", ""),
            "cached": cached,
        }

    sig_src = json.dumps(
        {
            "lang": payload["lang"],
            "status": payload["status"],
            "plan_tier": payload["plan_tier"],
            "groups": payload["groups"],
            "models": payload["models"],
            "message": payload["message"],
        },
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
    payload["sig"] = hashlib.sha1(sig_src).hexdigest()[:12]
    return payload


def collect_quota(lang="zh", force=False):
    """Collect live quota summary from host-injected Language Server env vars with TTL caching."""
    eff_lang = normalize_lang(lang)
    endpoint = parse_ls_endpoint()
    if endpoint is None:
        return _build_quota_response(None, "unconfigured", lang=eff_lang, cached=False)

    ep_sig = (endpoint["host"], endpoint["port"], endpoint["schemes"], endpoint["csrf"])
    ttl = _get_quota_ttl()
    now = time.monotonic()

    if not force:
        with QUOTA_CACHE_LOCK:
            if (
                QUOTA_CACHE["raw"] is not None
                and QUOTA_CACHE["sig"] == ep_sig
                and (now - QUOTA_CACHE["ts"]) < ttl
            ):
                return _build_quota_response(QUOTA_CACHE["raw"], "ok", lang=eff_lang, cached=True)

    raw_snap = _fetch_raw_quota_snapshot(endpoint)
    with QUOTA_CACHE_LOCK:
        QUOTA_CACHE["sig"] = ep_sig
        QUOTA_CACHE["ts"] = time.monotonic()
        QUOTA_CACHE["raw"] = raw_snap

    return _build_quota_response(raw_snap, "ok" if raw_snap.get("ok") else "unreachable", lang=eff_lang, cached=False)
