"""Model identifier normalization, family bucketing, and color palette definitions."""

import re

UNKNOWN_MODEL_LABEL = "未记录 (历史日志)"
MODEL_SEL_RE = re.compile(r"Model Selection`\s+from\s+(.+?)\s+to\s+(.+?)(?:\.\s|\.$|\r?\n|$)")
EFFORT_TAGS = {"xhigh", "high", "medium", "low", "minimal", "thinking", "fast"}

MODEL_PALETTE = [
    "#3b82f6", "#8b5cf6", "#06b6d4", "#10b981", "#f59e0b",
    "#ec4899", "#6366f1", "#14b8a6", "#f97316", "#84cc16",
]

FAMILY_COLORS = {
    "Gemini": "#3b82f6",
    "Claude": "#f59e0b",
    "Orchestrator": "#8b5cf6",
    "GPT": "#10b981",
    "其他": "#06b6d4",
    "未记录": "#94a3b8",
}


def normalize_model_name(raw):
    """Unify raw model slugs and human display names, stripping thinking/effort tiers."""
    if not raw:
        return ""
    s = str(raw).strip()
    if not s or s.lower() == "none":
        return ""
    if " " in s:
        m_eff = re.match(r"^(.*?)\s+\(([^)]+)\)$", s)
        if m_eff and m_eff.group(2).strip().lower() in EFFORT_TAGS:
            return m_eff.group(1).strip()
        return s

    low = s.lower()
    for suf in EFFORT_TAGS:
        if low.endswith("-" + suf):
            s = s[:-(len(suf) + 1)]
            low = s.lower()
            break

    m = re.match(r"^gemini-(\d+(?:\.\d+)?)-(.+)$", low)
    if m:
        ver, rest = m.group(1), m.group(2)
        seg = rest.split("-")
        if "." not in ver and len(seg) >= 2 and seg[0].isdigit():
            ver = f"{ver}.{seg[0]}"
            seg = seg[1:]
        words = ["OSS" if w == "oss" else w.capitalize() for w in seg if w]
        return f"Gemini {ver} {' '.join(words)}".strip()

    m = re.match(r"^claude-(opus|sonnet|haiku)-(\d+)-(\d+)$", low)
    if m:
        return f"Claude {m.group(1).capitalize()} {m.group(2)}.{m.group(3)}"

    m = re.match(r"^gpt-oss-(\d+b)$", low)
    if m:
        return f"GPT-OSS {m.group(1).upper()}"

    parts = [p.upper() if p in ("gpt", "oss") else p.capitalize() for p in low.split("-") if p]
    return " ".join(parts).strip()


def get_model_family(name):
    """Map normalized model display name to high-level vendor/family bucket."""
    if not name or name == UNKNOWN_MODEL_LABEL:
        return "未记录"
    low = name.lower()
    if low.startswith("gemini"):
        return "Gemini"
    if low.startswith("claude"):
        return "Claude"
    if low.startswith("gpt"):
        return "GPT"
    if low.startswith("orchestrator"):
        return "Orchestrator"
    return "其他"
