"""Runtime configuration, data directory discovery, and time-range helpers."""

import os
from datetime import datetime, timedelta

CACHE_SCHEMA_VERSION = "v4"

DEFAULT_DATA_DIRS = (
    os.path.expanduser("~/.gemini/antigravity"),
    os.path.expanduser("~/.gemini/antigravity-cli"),
    os.path.expanduser("~/.gemini/antigravity-ide"),
)

# Estimated billing reference rates (CNY per 1M tokens) and context window capacity.
PRICE_INPUT_PER_M = 0.54
PRICE_CACHE_PER_M = 0.135
PRICE_OUTPUT_PER_M = 2.16
CONTEXT_WINDOW_TOKENS = 1048576
DEFAULT_OUTPUT_SPEED = 198.0

TIME_RANGE_LABELS = {
    "today": ("今天", "今日活跃会话", 1),
    "7d": ("7天", "近 7 天会话", 7),
    "30d": ("30天", "近 30 天会话", 30),
    "all": ("全部", "全部会话", None),
}


def get_data_dirs():
    """Return Antigravity state root directories, honoring ANTIGRAVITY_DATA_DIRS."""
    override = os.environ.get("ANTIGRAVITY_DATA_DIRS", "").strip()
    if override:
        return [os.path.expanduser(p.strip()) for p in override.split(os.pathsep) if p.strip()]
    return list(DEFAULT_DATA_DIRS)


def get_brain_dirs():
    """Return transcript brain directories across configured data roots."""
    return [os.path.join(d, "brain") for d in get_data_dirs()]


def get_presence_dirs():
    """Return active session lock presence directories across configured data roots."""
    return [os.path.join(d, "presence") for d in get_data_dirs()]


DATA_DIRS = get_data_dirs()
BRAIN_DIRS = get_brain_dirs()
PRESENCE_DIRS = get_presence_dirs()


def normalize_time_range(raw):
    """Normalize query range parameter to today | 7d | 30d | all."""
    val = (raw or "all").strip().lower()
    return val if val in TIME_RANGE_LABELS else "all"


def get_time_range_bounds(raw):
    """Return (range_key, start_local, now_local, start_utc, short_label, session_kpi_label)."""
    key = normalize_time_range(raw)
    short_label, kpi_label, days = TIME_RANGE_LABELS[key]
    local_tz = datetime.now().astimezone().tzinfo
    now_local = datetime.now(local_tz)
    if days is None:
        return key, None, now_local, None, short_label, kpi_label
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    start_local = today_start - timedelta(days=days - 1)
    start_utc = start_local.astimezone(timezone_utc())
    return key, start_local, now_local, start_utc, short_label, kpi_label


def timezone_utc():
    """Return datetime.timezone.utc without polluting module wildcard namespace."""
    from datetime import timezone
    return timezone.utc
