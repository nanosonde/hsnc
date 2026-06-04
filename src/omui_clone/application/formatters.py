"""Display formatting helpers shared by use cases."""

from __future__ import annotations


def humanize_uptime(seconds: int) -> str:
    """Format a duration compactly: ``2d 3h``, ``26m 58s``, ``5s``."""

    if seconds <= 0:
        return "-"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
