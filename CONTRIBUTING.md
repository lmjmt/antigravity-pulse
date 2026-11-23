# Contributing to Antigravity Pulse

感谢关注 **Antigravity Pulse**！项目坚持 **纯 Python 3.9+ 标准库后端 + 零打包原生前端（Zero-Build Web）** 原则，保持轻量、安全与免编译热更新特性。

## 开发环境要求

- Python `3.9+`（仅标准库，无需 `pip install`）
- Node.js `18+`（仅用于 `node --check` 静态语法检查，运行期不依赖 Node）

## 分层约定

- `sidecars/task_monitor/server.py`：常驻 HTTP 宿主壳（端口/PID/Token 锁定、回环 CORS 白名单、多文件签名热加载器）。
- `sidecars/task_monitor/monitor_core.py`：热加载入口门面（清理 `core.*` 子模块、实例化引擎并执行缓存零丢失迁移）。
- `sidecars/task_monitor/core/`：按职责拆分的纯 Python 业务逻辑包（配置、格式化、模型归因、SQLite 存储、Swarm 解析、时间线诊断、多任务引擎、聚合分析、缓存迁移、HTTP 路由与静态资源安全服务）。
- `sidecars/task_monitor/web/`：原生 HTML/CSS/ES6 Modular UI（所有动态内容插入 `innerHTML` / HTML 属性前必须经 `escHtml()` 转义）。

## 提交前本地校验

提交 Merge Request 前，请确保通过全部本地检查：

```bash
./scripts/check.sh
```

检查涵盖：
1. `python3 -m compileall` 全量字节码编译检查
2. `node --check` 全量前端 JS 语法校验
3. `python3 -m unittest discover -s tests -v` 单元测试
4. 敏感路径 / 个人 ID 静态扫描（禁止提交本地用户名或个人会话 UUID）
