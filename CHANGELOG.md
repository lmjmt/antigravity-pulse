# Changelog

All notable changes to **Antigravity Pulse** are documented in this file.

## [1.0.0] - 2026-11-23

### Architecture & Open-Source Release
- Reorganized sidecar backend into clean layered modules under `sidecars/task_monitor/core/` (`config`, `formatting`, `models`, `storage`, `swarm`, `timeline`, `tasks`, `analytics`, `cache`, `router`).
- Split monolithic single-file frontend into clean native assets under `sidecars/task_monitor/web/` (`index.html`, `styles.css`, `js/{state,sessions,analytics,tasks,timeline,app}.js`) with path-traversal-hardened `/static/*` serving and `?v=<ui_version>` cache-busting.
- Extended `_HotCoreLoader` in `server.py` to watch `monitor_core.py` and all `core/*.py` files, reloading submodules cleanly with `CACHE_SCHEMA_VERSION = "v4"` zero-loss cache migration.
- Added `ANTIGRAVITY_DATA_DIRS` override and removed all host-specific paths or hardcoded conversation IDs for portable multi-platform deployment.
- Added standalone `unittest` suite (`tests/`), static verification script (`scripts/check.sh`), installer/sync script (`scripts/install.sh`), GitLab CI pipeline (`.gitlab-ci.yml`), and MIT License.

### Features Included
- **Model Usage Analytics**: 4-tier attribution (step `model` -> Swarm `members.json` -> `<USER_SETTINGS_CHANGE>` settings events + forward backfill -> subagent parent inheritance), thinking-tier normalization (`_EFFORT_TAGS`), dual-donut charts, vendor family mini-table, and 7-column sortable table with session cross-filtering.
- **Global Analytics & Context Inspector**: 4 time-range windows (`today`, `7d`, `30d`, `all`), dynamic usage series, 168-day activity heatmap, per-turn real-text fallback context timeline, spike/compaction detection, and OWASP XSS `escHtml(...)` output encoding across all DOM surfaces.
- **Real-Time Multi-Task & Swarm Monitor**: Master-detail focus inspector, concurrent grid/matrix views, step stream windowing, Swarm roster/board age tracking, and heartbeat stall diagnosis.
