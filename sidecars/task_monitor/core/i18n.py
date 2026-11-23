"""Lightweight English / Simplified Chinese localization helpers."""

TIME_RANGE_LABELS_I18N = {
    "zh": {
        "today": ("今天", "今日活跃会话", 1),
        "7d": ("7天", "近 7 天会话", 7),
        "30d": ("30天", "近 30 天会话", 30),
        "all": ("全部", "全部会话", None),
    },
    "en": {
        "today": ("Today", "Active Today", 1),
        "7d": ("7d", "Last 7d Sessions", 7),
        "30d": ("30d", "Last 30d Sessions", 30),
        "all": ("All", "All Sessions", None),
    },
}

MONTH_ABBR_EN = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr",
    5: "May", 6: "Jun", 7: "Jul", 8: "Aug",
    9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


def normalize_lang(raw, accept_language=""):
    """Normalize explicit lang query or Accept-Language header to 'zh' or 'en'."""
    val = (raw or "").strip().lower()
    if val:
        return "en" if val.startswith("en") else "zh"

    acc = (accept_language or "").strip().lower()
    if acc:
        for part in acc.split(","):
            code = part.split(";")[0].strip()
            if code.startswith("zh"):
                return "zh"
            if code.startswith("en"):
                return "en"
    return "zh"


def tr(lang, zh_text, en_text):
    """Select localized string between Simplified Chinese and English."""
    return en_text if lang == "en" else zh_text


def format_month_label(month_num, lang="zh"):
    """Format calendar month number for heatmap header ('6月' or 'Jun')."""
    if lang == "en":
        return MONTH_ABBR_EN.get(int(month_num), str(month_num))
    return f"{int(month_num)}月"


def format_relative_time(diff_seconds, lang="zh"):
    """Format elapsed seconds into concise relative timestamp ('5 分钟前' or '5m ago')."""
    if diff_seconds is None:
        return tr(lang, "未知", "Unknown")
    diff = max(0.0, float(diff_seconds))
    if diff < 60:
        return tr(lang, "刚刚", "Just now")
    if diff < 3600:
        mins = int(diff // 60)
        return f"{mins}m ago" if lang == "en" else f"{mins} 分钟前"
    if diff < 86400:
        hrs = int(diff // 3600)
        return f"{hrs}h ago" if lang == "en" else f"{hrs} 小时前"
    days = int(diff // 86400)
    return f"{days}d ago" if lang == "en" else f"{days} 天前"
