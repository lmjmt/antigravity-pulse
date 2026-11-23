---
name: antigravity-pulse
description: Bilingual (EN/ZH) real-time telemetry sidecar for Antigravity task execution, Swarm subagent trees, per-model token/call analytics, context bloat diagnosis, and stall alerts. / 中英双语实时监控 Antigravity 任务执行脉搏、Swarm 子代理拆解、模型用量统计、上下文演进诊断与防卡死预警。
---

# Antigravity Pulse Skill

Launch the native Auxiliary Pane dashboard for real-time task monitoring, multi-model token analytics, and session context diagnostics (supports instant `EN / 中` switching, `?lang=en|zh`, and `Accept-Language`).

提供一键在 Antigravity 辅助侧边栏打开中英双语任务进度、模型消耗与会话诊断大盘的能力。

## Usage / 使用方式

Click the pill below in chat to open or toggle the monitor panel in the Auxiliary Pane:

在对话中点击以下链接即可在辅助侧边栏展开监控盘：

[⚡ Open Antigravity Pulse / 打开监控盘](sidecar://antigravity-pulse/task_monitor/)

## Core Capabilities / 核心能力

- **Bilingual Telemetry (`EN / 中`) / 中英双语切换**：Supports zero-reparse runtime switching in the UI navbar plus `?lang=en|zh` and `Accept-Language` on every API endpoint. / 支持导航栏一键无刷新切换语言与全接口双语输出。
- **Model Usage Analytics / 模型使用量统计**：4-tier attribution, family/base-model dual donuts, and a 7-column sortable table for token usage, call counts, cache hit rate, and estimated cost, with click-to-filter session linking. / 四级模型归因、双环占比与 7 列可排序数据表，支持点击联动筛选下方会话。
- **Global Analytics & Context Drawer / 全局效能与上下文诊断**：Interactive KPIs, dynamic usage charts, 168-day activity heatmap, and per-session context evolution curves with `/compact` recommendations. / KPI 指标、趋势图、热力图与单会话上下文膨胀诊断抽屉。
- **Task & Swarm Topology / 主任务与协同层级树**：Real-time focus, grid, and matrix views for root tasks, subagents, Swarm message boards, and heartbeat stall diagnosis. / 实时追踪多任务、Swarm 成员动态与防卡死心跳告警。
