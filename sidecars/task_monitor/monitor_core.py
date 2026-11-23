#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Antigravity Pulse — Hot-Reload Core Façade
------------------------------------------
Loaded atomically by server.py on file updates. Flushes core.* submodules so
reloads always pick up fresh code while preserving all in-memory caches from
the previous monitor_core module instance.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Capture previous module BEFORE purging core.* so cache migration retains parsed state.
_PREV_MOD = sys.modules.get("monitor_core")

for _mod_name in list(sys.modules.keys()):
    if _mod_name == "core" or _mod_name.startswith("core."):
        del sys.modules[_mod_name]

from core.analytics import AntigravityAnalytics
from core.cache import migrate_caches_from as _migrate_caches
from core.config import CACHE_SCHEMA_VERSION
from core.router import WebAssetStore, dispatch_get as _dispatch_get
from core.storage import DB_CONVS_CACHE as _DB_CONVS_CACHE
from core.swarm import (
    SWARM_MODEL_MAP_CACHE as _SWARM_MODEL_MAP_CACHE,
    SWARM_STATE_CACHE as _SWARM_STATE_CACHE,
)
from core.tasks import AntigravityMultiTaskManager

analytics_engine = AntigravityAnalytics()
multi_task_manager = AntigravityMultiTaskManager(analytics_engine=analytics_engine)
asset_store = WebAssetStore(os.path.join(_HERE, "web"))


def migrate_caches_from(old_mod):
    """Preserve caches across reloads (delegates to core.cache.migrate_caches_from)."""
    return _migrate_caches(old_mod, analytics_engine, multi_task_manager)


def dispatch_get(path, qs, code_version="", reload_error=None):
    """Dispatch GET requests to modular router with initialized singletons."""
    return _dispatch_get(
        path,
        qs,
        analytics_engine=analytics_engine,
        multi_task_manager=multi_task_manager,
        asset_store=asset_store,
        code_version=code_version,
        reload_error=reload_error,
    )


# Eagerly inherit caches during exec_module while server.py still holds _PREV_MOD in sys.modules.
migrate_caches_from(_PREV_MOD)
