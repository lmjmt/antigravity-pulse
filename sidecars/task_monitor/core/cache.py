"""Zero-loss cache migration across atomic hot-reloads."""

from core.config import CACHE_SCHEMA_VERSION
from core.storage import DB_CACHE_LOCK, DB_CONVS_CACHE
from core.swarm import SWARM_CACHE_LOCK, SWARM_MODEL_MAP_CACHE, SWARM_STATE_CACHE

_MIGRATED_SOURCE_IDS = set()


def migrate_caches_from(old_mod, analytics_engine, multi_task_manager):
    """Preserve parsed transcript/meta/tail/steps/timeline/DB/Swarm caches across hot-reloads."""
    if old_mod is None:
        return False
    src_id = id(old_mod)
    if src_id in _MIGRATED_SOURCE_IDS:
        return False
    old_schema = getattr(old_mod, "CACHE_SCHEMA_VERSION", CACHE_SCHEMA_VERSION)
    if old_schema != CACHE_SCHEMA_VERSION:
        return False

    migrated = False
    old_db = getattr(old_mod, "_DB_CONVS_CACHE", None)
    if isinstance(old_db, dict) and old_db.get("rows") and DB_CONVS_CACHE.get("sig") is None:
        with DB_CACHE_LOCK:
            DB_CONVS_CACHE["sig"] = old_db.get("sig")
            DB_CONVS_CACHE["rows"] = list(old_db.get("rows") or [])
            migrated = True

    old_sw = getattr(old_mod, "_SWARM_STATE_CACHE", None)
    if isinstance(old_sw, dict) and old_sw and not SWARM_STATE_CACHE:
        with SWARM_CACHE_LOCK:
            SWARM_STATE_CACHE.update(old_sw.copy())
            migrated = True

    old_sw_map = getattr(old_mod, "_SWARM_MODEL_MAP_CACHE", None)
    if isinstance(old_sw_map, dict) and old_sw_map.get("sig") is not None and SWARM_MODEL_MAP_CACHE.get("sig") is None:
        with SWARM_CACHE_LOCK:
            SWARM_MODEL_MAP_CACHE["sig"] = old_sw_map.get("sig")
            SWARM_MODEL_MAP_CACHE["map"] = dict(old_sw_map.get("map") or {})
            migrated = True

    old_ana = getattr(old_mod, "analytics_engine", None)
    if old_ana is not None and old_ana is not analytics_engine:
        old_steps = getattr(old_ana, "_file_step_cache", None)
        old_meta = getattr(old_ana, "_file_meta_cache", None)
        old_tl = getattr(old_ana, "_timeline_cache", None)
        with analytics_engine._lock:
            if isinstance(old_steps, dict) and old_steps and not analytics_engine._file_step_cache:
                analytics_engine._file_step_cache.update(old_steps.copy())
                migrated = True
            if isinstance(old_meta, dict) and old_meta and not analytics_engine._file_meta_cache:
                analytics_engine._file_meta_cache.update(old_meta.copy())
                migrated = True
            if isinstance(old_tl, dict) and old_tl and not analytics_engine._timeline_cache:
                analytics_engine._timeline_cache.update(old_tl.copy())
                migrated = True

    old_mt = getattr(old_mod, "multi_task_manager", None)
    if old_mt is not None and old_mt is not multi_task_manager:
        old_tail = getattr(old_mt, "_tail_cache", None)
        old_full = getattr(old_mt, "_steps_full_cache", None)
        with multi_task_manager._lock:
            if isinstance(old_tail, dict) and old_tail and not multi_task_manager._tail_cache:
                multi_task_manager._tail_cache.update(old_tail.copy())
                migrated = True
            if isinstance(old_full, dict) and old_full and not multi_task_manager._steps_full_cache:
                multi_task_manager._steps_full_cache.update(old_full.copy())
                migrated = True

    _MIGRATED_SOURCE_IDS.add(src_id)
    return migrated
