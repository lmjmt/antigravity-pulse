---
name: antigravity-pulse
description: 实时监控 Antigravity 任务执行脉搏、Swarm 子代理拆解、模型用量统计、上下文演进诊断与防卡死预警。在辅助侧边栏原生打开大盘。
---

# Antigravity Pulse Skill

提供一键在 Antigravity 辅助侧边栏打开任务进度、模型消耗与会话诊断大盘的能力。

## 使用方式

在对话中点击以下链接即可在辅助侧边栏展开监控盘：

[⚡ 打开 Antigravity Pulse 监控盘](sidecar://antigravity-pulse/task_monitor/)

## 核心能力

- **模型使用量统计**：按模型系列与基础模型双环 + 7 列可排序数据表统计 Token 消耗、调用次数、均值与缓存命中率，支持点击联动筛选下方会话。
- **全局效能与会话大盘**：KPI 指标、按天/小时/周用量趋势图、84 天活跃度热力图与单会话上下文膨胀诊断抽屉。
- **主任务与子代理层级树**：实时追踪多任务与 Swarm 成员状态、消息板动态与防卡死心跳告警。
