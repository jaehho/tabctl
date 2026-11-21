"""Grouping rules: which tabs go into which group.

A rules file is TOML with one [[group]] table per rule:

    [[group]]
    title = "marimo"
    color = "blue"
    urls = ["http://127.0.0.1:*/?file=*"]

`urls` are shell-style patterns (`*`, `?`, `[...]`) matched against a
tab's whole address. A tab goes to the first rule it matches. Rules
gather ungrouped, unpinned tabs into the group of that title in the
tab's window, making it when there is none; a tab already in a group
stays there. The host applies them to each tab whose address changes,
and `tabctl apply` to every tab open.
"""

import fnmatch
import tomllib
from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from tabctl.model import COLORS, NO_GROUP, Group, Listing, Tab

RULE_KEYS = {"title", "urls", "color", "collapsed"}


@dataclass(frozen=True)
class Rule:
    title: str
    urls: tuple[str, ...]
    color: str | None = None
    collapsed: bool | None = None


@dataclass(frozen=True)
class JoinGroup:
    """Add tabs to an existing group."""

    tab_ids: tuple[int, ...]
    group_id: int


@dataclass(frozen=True)
class NewGroup:
    """Make a group of tabs in a window."""

    tab_ids: tuple[int, ...]
    window_id: int
    title: str
    color: str | None
    collapsed: bool | None


@dataclass(frozen=True)
class Recolor:
    """Give a group its rule's color."""

    group_id: int
    color: str


Step = JoinGroup | NewGroup | Recolor


def default_rules_path(environ: Mapping[str, str]) -> Path:
    """$XDG_CONFIG_HOME/tabctl/groups.toml, or under ~/.config."""
    config = environ.get("XDG_CONFIG_HOME") or Path("~/.config").expanduser()
    return Path(config) / "tabctl" / "groups.toml"


def parse_rules(document: dict) -> tuple[Rule, ...]:
    """The rules in a parsed file; ValueError says what is wrong."""
    tables = document.get("group", [])
    if not isinstance(tables, list):  # a user's file, not a caller's bug
        raise ValueError(  # noqa: TRY004
            "write each rule as a [[group]] table"
        )
    return tuple(parse_rule(i, t) for i, t in enumerate(tables, start=1))


def parse_rule(number: int, table: dict) -> Rule:
    """One [[group]] table; number says which in an error."""
    where = f"rule {number}"
    unknown = set(table) - RULE_KEYS
    if unknown:
        raise ValueError(f"{where}: unknown key {', '.join(sorted(unknown))}")
    title = table.get("title")
    if not isinstance(title, str) or not title:
        raise ValueError(f"{where}: needs a title")
    urls = table.get("urls")
    if (
        not isinstance(urls, list)
        or not urls
        or not all(isinstance(u, str) for u in urls)
    ):
        raise ValueError(f"{where} ({title}): urls must be a list of patterns")
    color = table.get("color")
    if color is not None and color not in COLORS:
        raise ValueError(
            f"{where} ({title}): color must be one of {', '.join(COLORS)}"
        )
    collapsed = table.get("collapsed")
    if collapsed is not None and not isinstance(collapsed, bool):
        raise ValueError(f"{where} ({title}): collapsed is true or false")
    return Rule(
        title=title, urls=tuple(urls), color=color, collapsed=collapsed
    )


def read_rules(path: Path) -> tuple[Rule, ...]:
    """The rules in the file at path."""
    with path.open("rb") as f:
        document = tomllib.load(f)
    try:
        return parse_rules(document)
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from None


def match_rule(url: str, rules: tuple[Rule, ...]) -> int | None:
    """Index of the first rule with a pattern matching url, if any."""
    for i, rule in enumerate(rules):
        if any(fnmatch.fnmatchcase(url, p) for p in rule.urls):
            return i
    return None


def plan_steps(listing: Listing, rules: tuple[Rule, ...]) -> tuple[Step, ...]:
    """What to change so tabs sit in their rules' groups, per window."""
    steps: list[Step] = []
    for window in listing.windows:
        tabs = sorted(
            (t for t in listing.tabs if t.window_id == window.id),
            key=lambda t: t.index,
        )
        groups = [g for g in listing.groups if g.window_id == window.id]
        steps += plan_window(window.id, tabs, groups, rules)
    return tuple(steps)


def plan_tab_steps(
    listing: Listing, rules: tuple[Rule, ...], tab_ids: Collection[int]
) -> tuple[Step, ...]:
    """plan_steps for these tabs alone, leaving group colors be."""
    only = replace(
        listing, tabs=tuple(t for t in listing.tabs if t.id in tab_ids)
    )
    steps = plan_steps(only, rules)
    return tuple(s for s in steps if not isinstance(s, Recolor))


def plan_window(
    window_id: int,
    tabs: list[Tab],
    groups: list[Group],
    rules: tuple[Rule, ...],
) -> list[Step]:
    """plan_steps for one window's tabs (in order) and groups."""
    claimed: dict[int, list[int]] = {}
    for tab in tabs:
        if tab.group_id != NO_GROUP or tab.pinned:
            continue
        i = match_rule(tab.url, rules)
        if i is not None:
            claimed.setdefault(i, []).append(tab.id)
    steps: list[Step] = []
    for i, rule in enumerate(rules):
        group = next((g for g in groups if g.title == rule.title), None)
        if group is not None and rule.color and group.color != rule.color:
            steps.append(Recolor(group_id=group.id, color=rule.color))
        tab_ids = tuple(claimed.get(i, ()))
        if not tab_ids:
            continue
        if group is not None:
            steps.append(JoinGroup(tab_ids=tab_ids, group_id=group.id))
        else:
            steps.append(
                NewGroup(
                    tab_ids=tab_ids,
                    window_id=window_id,
                    title=rule.title,
                    color=rule.color,
                    collapsed=rule.collapsed,
                )
            )
    return steps


def step_request(step: Step) -> tuple[str, dict]:
    """The extension command and arguments that carry out step."""
    match step:
        case JoinGroup(tab_ids=tab_ids, group_id=group_id):
            return "group", {"tabIds": list(tab_ids), "groupId": group_id}
        case NewGroup():
            return "group", {
                "tabIds": list(step.tab_ids),
                "windowId": step.window_id,
                "title": step.title,
                "color": step.color,
                "collapsed": step.collapsed,
            }
        case Recolor(group_id=group_id, color=color):
            return "edit-group", {"groupId": group_id, "color": color}
    raise TypeError(f"not a step: {step!r}")


def describe_step(step: Step, listing: Listing) -> str:
    """One line saying what step does, naming groups by title."""
    titles = {g.id: g.title for g in listing.groups}
    match step:
        case JoinGroup(tab_ids=tab_ids, group_id=group_id):
            return (
                f'add {count_tabs(tab_ids)} to "{titles[group_id]}" '
                f"(group {group_id})"
            )
        case NewGroup():
            color = f" {step.color}" if step.color else ""
            return (
                f'group {count_tabs(step.tab_ids)} as "{step.title}"{color} '
                f"in window {step.window_id}"
            )
        case Recolor(group_id=group_id, color=color):
            return f'color "{titles[group_id]}" (group {group_id}) {color}'
    raise TypeError(f"not a step: {step!r}")


def count_tabs(tab_ids: tuple[int, ...]) -> str:
    """'1 tab' or 'n tabs'."""
    return f"{len(tab_ids)} tab" + ("" if len(tab_ids) == 1 else "s")
