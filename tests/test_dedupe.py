import unittest

from tabctl.dedupe import Closure, plan_closures, same_page_key
from tabctl.model import NO_GROUP, Listing, Tab, Window


def make_tab(tab_id, url, *, window_id=1, last_accessed=0, **flags):
    return Tab(
        id=tab_id,
        window_id=window_id,
        index=tab_id,
        group_id=flags.get("group_id", NO_GROUP),
        url=url,
        title="",
        active=flags.get("active", False),
        pinned=flags.get("pinned", False),
        last_accessed=last_accessed,
    )


def make_listing(tabs, *, private_windows=()):
    window_ids = sorted({t.window_id for t in tabs})
    return Listing(
        windows=tuple(
            Window(id=w, focused=False, incognito=w in private_windows)
            for w in window_ids
        ),
        groups=(),
        tabs=tuple(tabs),
    )


class SamePageKey(unittest.TestCase):
    def test_ignores_the_fragment_and_loopback_spelling(self):
        self.assertEqual(
            same_page_key("http://localhost:2718/?file=a.py#cell"),
            same_page_key("http://127.0.0.1:2718/?file=a.py"),
        )

    def test_keeps_the_query_and_port(self):
        keys = {
            same_page_key(u)
            for u in (
                "http://127.0.0.1:2718/?file=a.py",
                "http://127.0.0.1:2718/?file=b.py",
                "http://127.0.0.1:2719/?file=a.py",
            )
        }
        self.assertEqual(len(keys), 3)


class PlanClosures(unittest.TestCase):
    def test_keeps_the_tab_used_last(self):
        listing = make_listing(
            [
                make_tab(1, "https://a.org/", last_accessed=10),
                make_tab(2, "https://a.org/#x", last_accessed=30),
                make_tab(3, "https://a.org/", last_accessed=20),
                make_tab(4, "https://b.org/"),
            ]
        )
        self.assertEqual(
            plan_closures(listing),
            (Closure(tab_id=1, kept_id=2), Closure(tab_id=3, kept_id=2)),
        )

    def test_prefers_pinned_then_active_then_grouped(self):
        cases = {
            "pinned": {"pinned": True},
            "active": {"active": True},
            "grouped": {"group_id": 5},
        }
        for name, flags in cases.items():
            with self.subTest(name):
                listing = make_listing(
                    [
                        make_tab(1, "https://a.org/", last_accessed=99),
                        make_tab(2, "https://a.org/", **flags),
                    ]
                )
                self.assertEqual(
                    plan_closures(listing), (Closure(tab_id=1, kept_id=2),)
                )

    def test_never_closes_a_pinned_tab(self):
        listing = make_listing(
            [
                make_tab(1, "https://a.org/", pinned=True),
                make_tab(2, "https://a.org/", pinned=True, last_accessed=5),
            ]
        )
        self.assertEqual(plan_closures(listing), ())

    def test_private_and_normal_windows_are_apart(self):
        listing = make_listing(
            [
                make_tab(1, "https://a.org/", window_id=1),
                make_tab(2, "https://a.org/", window_id=2),
            ],
            private_windows=(2,),
        )
        self.assertEqual(plan_closures(listing), ())

    def test_finds_duplicates_across_windows(self):
        listing = make_listing(
            [
                make_tab(1, "https://a.org/", window_id=1, last_accessed=1),
                make_tab(2, "https://a.org/", window_id=2, last_accessed=2),
            ]
        )
        self.assertEqual(
            plan_closures(listing), (Closure(tab_id=1, kept_id=2),)
        )


if __name__ == "__main__":
    unittest.main()
