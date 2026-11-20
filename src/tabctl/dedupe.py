"""Duplicate tabs: tabs showing the same page as another.

Two tabs show the same page when their addresses match less any
#fragment, with localhost and 127.0.0.1 taken as one host, in windows
of the same kind (private or not). Of each set one tab stays: a pinned
one, else the active one, else one in a group, else the one used last.
Pinned tabs are never closed.
"""

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from tabctl.model import NO_GROUP, Listing, Tab

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1"})


@dataclass(frozen=True)
class Closure:
    """Close tab_id, which shows the same page as kept_id."""

    tab_id: int
    kept_id: int


def same_page_key(url: str) -> str:
    """url less its #fragment, with localhost written 127.0.0.1."""
    parts = urlsplit(url)
    netloc = parts.netloc
    if parts.hostname in LOOPBACK_HOSTS:
        netloc = netloc.replace(parts.hostname, "127.0.0.1", 1)
    return urlunsplit(parts._replace(netloc=netloc, fragment=""))


def keep_priority(tab: Tab) -> tuple:
    """Sort key: the highest is the tab of a set to keep."""
    return (
        tab.pinned,
        tab.active,
        tab.group_id != NO_GROUP,
        tab.last_accessed,
    )


def plan_closures(listing: Listing) -> tuple[Closure, ...]:
    """The tabs to close so each page is open once, in tab order."""
    private = {w.id: w.incognito for w in listing.windows}
    by_page: dict[tuple[bool, str], list[Tab]] = {}
    for tab in sorted(listing.tabs, key=lambda t: (t.window_id, t.index)):
        key = (private.get(tab.window_id, False), same_page_key(tab.url))
        by_page.setdefault(key, []).append(tab)
    closures = []
    for tabs in by_page.values():
        kept = max(tabs, key=keep_priority)
        closures += [
            Closure(tab_id=t.id, kept_id=kept.id)
            for t in tabs
            if t is not kept and not t.pinned
        ]
    order = {t.id: (t.window_id, t.index) for t in listing.tabs}
    return tuple(sorted(closures, key=lambda c: order[c.tab_id]))
