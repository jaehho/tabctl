"""Stale tabs: tabs not used for a while.

Firefox's lastAccessed is when a tab was last left, or when it was
made if it was never shown; the tab on show in each window reads as in
use now. Pinned tabs are never stale.
"""

import re

from tabctl.model import Listing, Tab

UNIT_SECONDS = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}
AGE_PATTERN = re.compile(r"(\d+)([wdhms])")


def parse_age(text: str) -> int:
    """Seconds in an age written like 30m, 12h, 7d or 2w."""
    match = AGE_PATTERN.fullmatch(text)
    if match is None:
        raise ValueError(f"not an age: {text!r} (write 30m, 12h, 7d or 2w)")
    return int(match[1]) * UNIT_SECONDS[match[2]]


def format_age(seconds: float) -> str:
    """seconds in its largest whole unit up to days: 40s, 5h, 9d."""
    for unit in "dhm":
        if seconds >= UNIT_SECONDS[unit]:
            return f"{int(seconds // UNIT_SECONDS[unit])}{unit}"
    return f"{max(int(seconds), 0)}s"


def find_stale_tabs(listing: Listing, *, cutoff_ms: int) -> tuple[Tab, ...]:
    """Unpinned tabs last used before cutoff_ms, in tab order.

    A tab without a lastAccessed (0, from extension 0.1.0) is left out.
    """
    stale = (
        t
        for t in listing.tabs
        if not t.pinned and 0 < t.last_accessed < cutoff_ms
    )
    return tuple(sorted(stale, key=lambda t: (t.window_id, t.index)))
