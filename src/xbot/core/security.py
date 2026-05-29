from __future__ import annotations

import os


def is_agent_admin_mode_allowed() -> bool:
    return os.getenv("XBOT_AGENT_ADMIN_MODE_ALLOWED", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
        "admin",
    }
