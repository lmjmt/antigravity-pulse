#!/usr/bin/env python3
"""Inject a bilingual quick sidecar launch hint into new Antigravity sessions."""

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
                        "💡 [Antigravity Pulse] Ready / 已就绪: "
                        "[⚡ Antigravity Pulse](sidecar://antigravity-pulse/task_monitor/) "
                        "— Live task topology, model telemetry & stall diagnostics / 实时任务监控、模型用量与防卡死诊断。"
                    )
                }
            }
        ]
    }
    sys.stdout.write(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
