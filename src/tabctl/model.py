"""Windows, tab groups and tabs, as the extension reports them."""

from dataclasses import dataclass

NO_GROUP = -1
COLORS = (
    "blue",
    "cyan",
    "grey",
    "green",
    "orange",
    "pink",
    "purple",
    "red",
    "yellow",
)


@dataclass(frozen=True)
class Window:
    id: int
    focused: bool
    incognito: bool


@dataclass(frozen=True)
class Group:
    id: int
    window_id: int
    title: str
    color: str
    collapsed: bool


@dataclass(frozen=True)
class Tab:
    id: int
    window_id: int
    index: int
    group_id: int
    url: str
    title: str
    active: bool
    pinned: bool


@dataclass(frozen=True)
class Listing:
    windows: tuple[Window, ...]
    groups: tuple[Group, ...]
    tabs: tuple[Tab, ...]


def parse_group(raw: dict) -> Group:
    """A group as the extension reports it."""
    return Group(
        id=raw["id"],
        window_id=raw["windowId"],
        title=raw["title"],
        color=raw["color"],
        collapsed=raw["collapsed"],
    )


def parse_listing(raw: dict) -> Listing:
    """The extension's `list` result, as typed records."""
    return Listing(
        windows=tuple(
            Window(id=w["id"], focused=w["focused"], incognito=w["incognito"])
            for w in raw["windows"]
        ),
        groups=tuple(parse_group(g) for g in raw["groups"]),
        tabs=tuple(
            Tab(
                id=t["id"],
                window_id=t["windowId"],
                index=t["index"],
                group_id=t["groupId"],
                url=t["url"],
                title=t["title"],
                active=t["active"],
                pinned=t["pinned"],
            )
            for t in raw["tabs"]
        ),
    )


def format_listing(listing: Listing) -> str:
    """Windows, then their tabs in order, each group above its tabs.

    A tab line is its id, `*` if it is the window's active tab, its
    title and its address.
    """
    groups = {g.id: g for g in listing.groups}
    lines = []
    for window in listing.windows:
        notes = ", focused" if window.focused else ""
        notes += ", private" if window.incognito else ""
        lines.append(f"window {window.id}{notes}")
        tabs = sorted(
            (t for t in listing.tabs if t.window_id == window.id),
            key=lambda t: t.index,
        )
        shown_group = NO_GROUP
        for tab in tabs:
            if tab.group_id != shown_group and tab.group_id in groups:
                lines.append("  " + format_group(groups[tab.group_id]))
            shown_group = tab.group_id
            indent = "    " if tab.group_id in groups else "  "
            mark = "*" if tab.active else " "
            lines.append(f"{indent}{tab.id:>4} {mark} {tab.title}  {tab.url}")
    return "\n".join(lines)


def format_group(group: Group) -> str:
    """A group's heading line: id, title, color, collapsed or not."""
    folded = ", collapsed" if group.collapsed else ""
    return f'group {group.id} "{group.title}" {group.color}{folded}'
