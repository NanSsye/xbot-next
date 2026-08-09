from datetime import UTC, datetime


def utc_now() -> datetime:
    """当前 UTC 时间，naive（统一存储格式，避免与 naive UTC 混用时区）。"""
    return datetime.now(UTC).replace(tzinfo=None)
