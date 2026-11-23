#!/usr/bin/env python3
"""Inject a quick sidecar launch hint into new Antigravity sessions."""

import json
import sys


def main():
    try:
        json.load(sys.stdin)
    except Exception:
        pass

    result = {
        "injectSteps": [
            {
                "systemMessage": {
                    "systemMessage": (
                        "💡 [Antigravity Pulse] 已就绪：随时点击 "
                        "[⚡ 打开 Antigravity Pulse 监控盘](sidecar://antigravity-pulse/task_monitor/) "
                        "可在侧边栏查看任务步骤拓扑、模型用量与防卡死诊断。"
                    )
                }
            }
        ]
    }
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
