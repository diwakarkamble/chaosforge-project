from datetime import timezone

from chaosforge.application.services.user_settings import get_timezone


def format_report_time(dt, timezone_id=None):
    report_timezone = get_timezone(timezone_id)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    dt = dt.astimezone(report_timezone)

    offset = dt.strftime("%z")
    offset = f"UTC{offset[:3]}:{offset[3:]}"

    return f"{dt.strftime('%d-%b-%Y %H:%M:%S %Z')} ({offset}, {report_timezone.key})"
