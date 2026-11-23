**English** | [中文](#中文贡献指南)

# Contributing to Antigravity Pulse

Thank you for contributing to **Antigravity Pulse**. The project adheres strictly to a **pure Python 3.9+ standard-library backend + zero-build native web frontend** architecture to preserve instant startup, zero external dependencies, and atomic hot-reloading.

## Requirements

- Python `3.9+` (standard library only — no `pip install` needed; avoid backslashes inside `{...}` in f-strings for Python 3.9 compatibility)
- Node.js `18+` (used during verification for `node --check` and frontend i18n key-parity tests; not required at runtime)

## Architecture Conventions

- `sidecars/task_monitor/server.py`: Resident HTTP host shell (IDE port/PID/token lock, loopback-only CORS allowlist, multi-file signature hot reloader).
- `sidecars/task_monitor/monitor_core.py`: Hot-reload facade (reloads `core.*` modules atomically and performs zero-loss cache migration).
- `sidecars/task_monitor/core/`: 11 single-responsibility Python modules (`config`, `i18n`, `formatting`, `models`, `storage`, `swarm`, `timeline`, `tasks`, `analytics`, `cache`, `router`).
  - Keep transcript/SQLite parse caches strictly **language-agnostic**; localize output via `core/i18n.py` (`tr(lang, zh_text, en_text)`).
- `sidecars/task_monitor/web/`: Native HTML, CSS, and 7 zero-build ES6 modules (`i18n.js`, `state.js`, `sessions.js`, `analytics.js`, `tasks.js`, `timeline.js`, `app.js`).
  - Every `I18N.zh` and `I18N.en` dictionary key in `web/js/i18n.js` **must remain symmetric**.
  - Inside scopes with local `t` variables (`state.js`, `tasks.js`, `timeline.js`), use `i18n(key, vars)` instead of `t(key, vars)`.
  - Never add `localStorage` or `IndexedDB` persistence; keep client preferences volatile.
  - Escape all dynamic strings before injecting into `innerHTML` or HTML attributes via `escHtml()`.

## Pre-Commit Verification

Run all automated checks locally before opening a Pull / Merge Request:

```bash
./scripts/check.sh
```

The suite verifies:
1. Full Python bytecode compilation (`python3 -m compileall`)
2. Frontend ES6 syntax across all JS modules (`node --check`)
3. Offline `unittest` suite (`python3 -m unittest discover -s tests -v`), including `tests/test_i18n.py`
4. Privacy & portability scan (blocks local usernames/home paths, runtime UUIDs, and non-noreply emails)

---

## 中文贡献指南

感谢关注 **Antigravity Pulse**！本项目坚持 **纯 Python 3.9+ 标准库后端 + 零打包原生前端（Zero-Build Web）** 架构，请遵循以下规范：

- **缓存语言无关**：`core/` 中文件解析缓存严禁绑定语言，所有文本本地化统一经 `core/i18n.py` 根据 `lang`（`zh` / `en`）实时生成。
- **前端双语对称与安全**：修改 `sidecars/task_monitor/web/js/i18n.js` 时需保证 `I18N.zh` 与 `I18N.en` 键集合完全一致；在存在局部变量 `t` 的函数作用域内请统一调用 `i18n(...)`；所有动态文本写入 DOM 前须经过 `escHtml()`，且不得引入 `localStorage` / `IndexedDB`。
- **提交前校验**：提交前请务必执行 `./scripts/check.sh`，确保编译、JS 语法检查、单元测试（含 `tests/test_i18n.py`）与隐私路径扫描全部通过。
