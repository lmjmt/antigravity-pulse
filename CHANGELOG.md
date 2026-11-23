# Changelog

All notable changes to **Antigravity Pulse** are documented in this file.

## [1.2.0] - 2026-11-23

### Cross-Platform Installer, Preflight Doctor & CI/Release Automation
- **Unified Cross-Platform Installer (`scripts/install.py`)**:
  - Added zero-dependency Python 3.9+ installer supporting `--doctor`, `--update`, `--uninstall`, `--sync-sidecar <dir>`, `--dry-run`, `--version <ref>`, `--archive-url`, and `--sha256` verification with TarSlip/symlink extraction guards.
  - Added preflight checks for Python version (`>= 3.9`), Antigravity data directories, and legacy `task-monitor` plugin conflict warnings.
  - Upgraded `scripts/install.sh` to support both local execution and one-line remote `curl | bash` installation, and added native Windows `scripts/install.ps1` (`irm | iex`).
- **Plugin Assets & Bilingual Hook**:
  - Added vector plugin icon `assets/logo.svg` and updated `hooks/on_session_start.py` with concise EN/ZH launch guidance.
- **GitHub Actions CI & Release Workflows**:
  - Added `.github/workflows/ci.yml` (`ubuntu-latest` + `macos-latest`) and `.github/workflows/release.yml` (automated `.tar.gz`, `.zip`, and `SHA256SUMS.txt` on `v*` tags).
- **Installer Test Suite**:
  - Added `tests/test_installer.py` covering doctor checks, dry-run/install/uninstall lifecycle, `--sync-sidecar`, SHA256 validation, and TarSlip blocking.

## [1.1.0] - 2026-11-23

### Bilingual Support (English & Simplified Chinese)
- **Backend & API i18n (`core/i18n.py`)**:
  - Added `?lang=zh|en` query parameter and `Accept-Language` header negotiation across `/`, `/api/health`, `/api/all`, `/api/analytics`, `/api/sessions`, `/api/multi_task`, `/api/session/context_timeline`, and `/api/task_steps`.
  - Kept file-level transcript and SQLite parse caches strictly language-agnostic (`CACHE_SCHEMA_VERSION = "v4"`), localizing only response outputs in `core/{config,models,timeline,analytics,tasks,router}.py` for 0 ms language switching.
  - Standardized legacy unknown-month filter keys to `"unknown"` across backend (`core/analytics.py`) and frontend (`web/js/sessions.js`).
- **Frontend i18n (`web/js/i18n.js`)**:
  - Added symmetric `I18N.zh` and `I18N.en` dictionaries, volatile state hydration from `INITIAL_PAYLOAD.lang`, `data-i18n*` DOM attribute translation (`applyStaticI18n`), safe `i18n()` alias (avoiding local `t` shadowing in `state.js`, `tasks.js`, and `timeline.js`), and a top-navbar **`EN / 中`** switcher (`toggleLanguage()`).
  - Propagated `&lang=` across all live polling and on-demand `fetch()` calls with race guards (`reqLang !== currentLang`).
- **Bilingual Documentation & Verification**:
  - Added `README.zh-CN.md` and promoted English `README.md` as default open-source landing documentation with top language switchers.
  - Updated `CONTRIBUTING.md`, `plugin.json` (`v1.1.0`), `sidecars/task_monitor/sidecar.json`, and `skills/antigravity-pulse/SKILL.md`.
  - Added automated bilingual test suite `tests/test_i18n.py` verifying `normalize_lang`, full API `zh`/`en` output parity, zero CJK leakage on `lang=en`, frontend dictionary key parity, and shadow-safe translation calls.

## [1.0.0] - 2026-11-23

### Architecture & Open-Source Release
- Reorganized sidecar backend into clean layered modules under `sidecars/task_monitor/core/` (`config`, `formatting`, `models`, `storage`, `swarm`, `timeline`, `tasks`, `analytics`, `cache`, `router`).
- Split monolithic single-file frontend into clean native assets under `sidecars/task_monitor/web/` (`index.html`, `styles.css`, `js/{state,sessions,analytics,tasks,timeline,app}.js`) with path-traversal-hardened `/static/*` serving and `?v=<ui_version>` cache-busting.
- Extended `_HotCoreLoader` in `server.py` to watch `monitor_core.py` and all `core/*.py` files, reloading submodules cleanly with `CACHE_SCHEMA_VERSION = "v4"` zero-loss cache migration.
- Added `ANTIGRAVITY_DATA_DIRS` override and removed all host-specific paths or hardcoded conversation IDs for portable multi-platform deployment.
- Added standalone `unittest` suite (`tests/`), static verification script (`scripts/check.sh`), installer/sync script (`scripts/install.sh`), GitLab CI pipeline (`.gitlab-ci.yml`), and MIT License.

### Features Included
- **Model Usage Analytics**: 4-tier attribution (step `model` -> Swarm `members.json` -> `<USER_SETTINGS_CHANGE>` settings events + forward backfill -> subagent parent inheritance), thinking-tier normalization (`_EFFORT_TAGS`), dual-donut charts, vendor family mini-table, and 7-column sortable table with session cross-filtering.
- **Global Analytics & Context Inspector**: 4 time-range windows (`today`, `7d`, `30d`, `all`), dynamic usage series, 168-day activity heatmap, per-turn real-text fallback context timeline, spike/compaction detection, and OWASP XSS `escHtml()` output encoding across all DOM surfaces.
- **Real-Time Multi-Task & Swarm Monitor**: Master-detail focus inspector, concurrent grid/matrix views, step stream windowing, Swarm roster/board age tracking, and heartbeat stall diagnosis.
