import unittest

from tabctl.model import NO_GROUP, Listing, Tab, Window
from tabctl.stale import find_stale_tabs, format_age, parse_age

DAY_MS = 86_400_000
NOW_MS = 100 * DAY_MS


def make_tab(tab_id, *, idle_days, window_id=1, **flags):
    return Tab(
        id=tab_id,
        window_id=window_id,
        index=flags.get("index", tab_id),
        group_id=flags.get("group_id", NO_GROUP),
        url=f"https://example.org/{tab_id}",
        title="",
        active=False,
        pinned=flags.get("pinned", False),
        last_accessed=flags.get("last_accessed", NOW_MS - idle_days * DAY_MS),
    )


def make_listing(tabs):
    return Listing(
        windows=tuple(
            Window(id=w, focused=False, incognito=False)
            for w in sorted({t.window_id for t in tabs})
        ),
        groups=(),
        tabs=tuple(tabs),
    )


def stale_ids(tabs, *, older_than_days):
    found = find_stale_tabs(
        make_listing(tabs), cutoff_ms=NOW_MS - older_than_days * DAY_MS
    )
    return [t.id for t in found]


class ParseAge(unittest.TestCase):
    def test_reads_each_unit(self):
        cases = {"45s": 45, "30m": 1800, "12h": 43200, "7d": 604800}
        for text, seconds in cases.items():
            self.assertEqual(parse_age(text), seconds, text)
        self.assertEqual(parse_age("2w"), 14 * 86400)

    def test_rejects_anything_else(self):
        for text in ("7", "d", "7 d", "1d12h", "-3d", "7D", ""):
            with self.assertRaisesRegex(ValueError, "not an age"):
                parse_age(text)


class FormatAge(unittest.TestCase):
    def test_gives_the_largest_whole_unit_up_to_days(self):
        self.assertEqual(format_age(40), "40s")
        self.assertEqual(format_age(12 * 60 + 59), "12m")
        self.assertEqual(format_age(5 * 3600), "5h")
        self.assertEqual(format_age(20 * 86400), "20d")


class FindStaleTabs(unittest.TestCase):
    def test_finds_tabs_unused_longer_than_the_age(self):
        tabs = [make_tab(1, idle_days=9), make_tab(2, idle_days=2)]
        self.assertEqual(stale_ids(tabs, older_than_days=7), [1])

    def test_a_tab_used_exactly_at_the_cutoff_stays(self):
        tabs = [make_tab(1, idle_days=7)]
        self.assertEqual(stale_ids(tabs, older_than_days=7), [])

    def test_never_closes_a_pinned_tab(self):
        tabs = [make_tab(1, idle_days=30, pinned=True)]
        self.assertEqual(stale_ids(tabs, older_than_days=7), [])

    def test_grouped_tabs_go_too(self):
        tabs = [make_tab(1, idle_days=30, group_id=5)]
        self.assertEqual(stale_ids(tabs, older_than_days=7), [1])

    def test_leaves_tabs_with_no_last_accessed(self):
        tabs = [make_tab(1, idle_days=0, last_accessed=0)]
        self.assertEqual(stale_ids(tabs, older_than_days=7), [])

    def test_lists_tabs_by_window_then_position(self):
        tabs = [
            make_tab(1, idle_days=9, window_id=2, index=0),
            make_tab(2, idle_days=9, window_id=1, index=1),
            make_tab(3, idle_days=9, window_id=1, index=0),
        ]
        self.assertEqual(stale_ids(tabs, older_than_days=7), [3, 2, 1])


if __name__ == "__main__":
    unittest.main()
