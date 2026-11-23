# Antigravity Pulse Rules

## Auto-Surfacing Task & Performance Monitor

For any multi-step workflow, Swarm coordination, subagent breakdown, long-running operation, or whenever the user asks about progress, model usage, context bloat, or whether tasks are stuck:

1. **Surface the sidecar viewer pill**: Include the exact clickable sidecar link in your chat response so the user can open the real-time monitor panel in the auxiliary pane with one click:
   `[⚡ Antigravity Pulse 监控盘](sidecar://antigravity-pulse/task_monitor/)`

2. **Proactive Hang Alerting**: If a background task or subagent takes longer than normal, point the user to the monitor panel to inspect heartbeat latency, active tool calls, and Swarm board messages.
