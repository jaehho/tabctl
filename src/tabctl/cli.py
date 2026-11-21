"""tabctl's command line."""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from tabctl import __version__
from tabctl.client import TabctlError, find_socket, send_request
from tabctl.dedupe import plan_closures
from tabctl.host import HostRunningError, run_host
from tabctl.model import (
    COLORS,
    format_group,
    format_listing,
    parse_group,
    parse_listing,
)
from tabctl.rules import (
    default_rules_path,
    describe_step,
    plan_steps,
    read_rules,
    step_request,
)
from tabctl.stale import find_stale_tabs, format_age, parse_age


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tabctl",
        description="List, focus, open and group Firefox tabs.",
    )
    parser.add_argument(
        "--version", action="version", version=f"tabctl {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ls = sub.add_parser("ls", help="list windows, groups and tabs")
    add_json(ls)

    open_ = sub.add_parser(
        "open",
        help="bring the tab showing URL forward, or open it in a new tab",
    )
    open_.add_argument("url")
    open_.add_argument(
        "--match-param",
        action="append",
        default=[],
        metavar="NAME",
        help="match a tab on origin, path and this query parameter "
        "(repeatable) instead of the whole address",
    )
    open_.add_argument(
        "--new", action="store_true", help="always open a new tab"
    )
    add_json(open_)

    group = sub.add_parser(
        "group", help="put tabs in a new group, or in GROUP_ID with --into"
    )
    group.add_argument("tab_ids", type=int, nargs="+", metavar="TAB_ID")
    group.add_argument("--into", type=int, metavar="GROUP_ID")
    add_looks(group)
    add_json(group)

    ungroup = sub.add_parser("ungroup", help="take tabs out of their groups")
    ungroup.add_argument("tab_ids", type=int, nargs="+", metavar="TAB_ID")

    close = sub.add_parser(
        "close", help="close tabs by id, or every tab unused for a while"
    )
    close.add_argument("tab_ids", type=int, nargs="*", metavar="TAB_ID")
    close.add_argument(
        "--older-than",
        metavar="AGE",
        help="instead of ids: every unpinned tab not used for AGE "
        "(30m, 12h, 7d, 2w)",
    )
    add_dry_run(close)
    add_json(close)

    dedupe = sub.add_parser(
        "dedupe",
        help="close tabs showing the same page as another, keeping one",
    )
    add_dry_run(dedupe)
    add_json(dedupe)

    edit = sub.add_parser(
        "edit-group", help="change a group's title, color or collapse"
    )
    edit.add_argument("group_id", type=int)
    add_looks(edit)
    add_json(edit)

    apply = sub.add_parser(
        "apply", help="sort ungrouped tabs into groups by the rules file"
    )
    apply.add_argument(
        "--rules",
        type=Path,
        metavar="FILE",
        help="rules file (default $XDG_CONFIG_HOME/tabctl/groups.toml)",
    )
    add_dry_run(apply)
    add_json(apply)

    # Firefox runs the host with the manifest's path and the
    # extension's id as arguments; neither is needed.
    host = sub.add_parser("native-host", help=argparse.SUPPRESS)
    host.add_argument("firefox_args", nargs="*")
    return parser


def add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json", action="store_true", help="print the result as JSON"
    )


def add_dry_run(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="only say what it would do",
    )


def add_looks(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--title")
    parser.add_argument("--color", choices=COLORS)
    folded = parser.add_mutually_exclusive_group()
    folded.add_argument(
        "--collapsed", dest="collapsed", action="store_true", default=None
    )
    folded.add_argument("--expanded", dest="collapsed", action="store_false")


def looks_args(args: argparse.Namespace) -> dict:
    return {
        "title": args.title,
        "color": args.color,
        "collapsed": args.collapsed,
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "native-host":
        try:
            asyncio.run(
                run_host(
                    find_socket(os.environ),
                    rules_path=default_rules_path(os.environ),
                )
            )
        except HostRunningError as error:
            print(f"tabctl native-host: {error}", file=sys.stderr)
            return 1
        return 0
    try:
        return run_command(args, find_socket(os.environ))
    except TabctlError as error:
        print(f"tabctl: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError) as error:
        print(f"tabctl: {error}", file=sys.stderr)
        return 1


def run_command(args: argparse.Namespace, socket_path: Path) -> int:
    def ask(command: str, request: dict):
        return send_request(socket_path, command, request)

    if args.command == "ls":
        raw = ask("list", {})
        emit(args, raw, format_listing(parse_listing(raw)))
    elif args.command == "open":
        result = ask(
            "open",
            {
                "url": args.url,
                "matchParams": args.match_param,
                "newTab": args.new,
            },
        )
        verb = "opened" if result["created"] else "focused"
        emit(args, result, f"{verb} tab {result['tab']['id']}")
    elif args.command == "group":
        request = {"tabIds": args.tab_ids, **looks_args(args)}
        if args.into is not None:
            request["groupId"] = args.into
        group = ask("group", request)
        emit(args, group, format_group(parse_group(group)))
    elif args.command == "ungroup":
        ask("ungroup", {"tabIds": args.tab_ids})
    elif args.command == "close":
        return close_tabs(args, ask)
    elif args.command == "dedupe":
        return close_duplicates(args, ask)
    elif args.command == "edit-group":
        group = ask(
            "edit-group", {"groupId": args.group_id, **looks_args(args)}
        )
        emit(args, group, format_group(parse_group(group)))
    elif args.command == "apply":
        return apply_rules(args, ask)
    return 0


def apply_rules(args: argparse.Namespace, ask) -> int:
    rules = read_rules(args.rules or default_rules_path(os.environ))
    listing = parse_listing(ask("list", {}))
    steps = plan_steps(listing, rules)
    lines = [describe_step(step, listing) for step in steps]
    if not args.dry_run:
        for step in steps:
            ask(*step_request(step))
    record = {
        "applied": not args.dry_run,
        "steps": [
            {"command": c, "args": a} for c, a in map(step_request, steps)
        ],
    }
    text = "\n".join(lines) if lines else "nothing to do"
    emit(args, record, text)
    return 0


def close_tabs(args: argparse.Namespace, ask) -> int:
    if args.older_than is not None:
        if args.tab_ids:
            raise ValueError("close takes tab ids or --older-than, not both")
        return close_stale(args, ask)
    if not args.tab_ids:
        raise ValueError("close takes tab ids or --older-than AGE")
    if args.dry_run or args.json:
        raise ValueError("--dry-run and --json go with --older-than")
    ask("close", {"tabIds": args.tab_ids})
    return 0


def close_stale(args: argparse.Namespace, ask) -> int:
    age_s = parse_age(args.older_than)
    listing = parse_listing(ask("list", {}))
    now_ms = time.time_ns() // 1_000_000
    stale = find_stale_tabs(listing, cutoff_ms=now_ms - age_s * 1000)
    if stale and not args.dry_run:
        ask("close", {"tabIds": [t.id for t in stale]})
    lines = [
        f"close {t.id:>4} "
        f"(unused {format_age((now_ms - t.last_accessed) / 1000)}) "
        f"{t.title}  {t.url}"
        for t in stale
    ]
    record = {
        "applied": not args.dry_run,
        "closures": [
            {"tabId": t.id, "lastAccessed": t.last_accessed} for t in stale
        ],
    }
    nothing = f"no tab unused for {args.older_than}"
    emit(args, record, "\n".join(lines) if lines else nothing)
    return 0


def close_duplicates(args: argparse.Namespace, ask) -> int:
    listing = parse_listing(ask("list", {}))
    closures = plan_closures(listing)
    if closures and not args.dry_run:
        ask("close", {"tabIds": [c.tab_id for c in closures]})
    tabs = {t.id: t for t in listing.tabs}
    lines = [
        f"close {c.tab_id:>4} (keeping {c.kept_id}) "
        f"{tabs[c.tab_id].title}  {tabs[c.tab_id].url}"
        for c in closures
    ]
    record = {
        "applied": not args.dry_run,
        "closures": [
            {"tabId": c.tab_id, "keptId": c.kept_id} for c in closures
        ],
    }
    emit(args, record, "\n".join(lines) if lines else "no duplicates")
    return 0


def emit(args: argparse.Namespace, record, text: str) -> None:
    print(json.dumps(record) if args.json else text)
