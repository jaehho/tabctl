import unittest

from tabctl.model import NO_GROUP, Group, Listing, Tab, Window
from tabctl.rules import (
    JoinGroup,
    NewGroup,
    Recolor,
    Rule,
    parse_rules,
    plan_steps,
    plan_tab_steps,
    step_request,
)


def make_tab(tab_id, url, *, window_id=1, group_id=NO_GROUP, pinned=False):
    return Tab(
        id=tab_id,
        window_id=window_id,
        index=tab_id,
        group_id=group_id,
        url=url,
        title="",
        active=False,
        pinned=pinned,
    )


def make_listing(tabs, groups=(), windows=(1,)):
    return Listing(
        windows=tuple(
            Window(id=w, focused=False, incognito=False) for w in windows
        ),
        groups=tuple(groups),
        tabs=tuple(tabs),
    )


NOTEBOOKS = Rule(
    title="notebooks", urls=("http://127.0.0.1:*/?file=*",), color="blue"
)
DOCS = Rule(title="docs", urls=("https://docs.*", "https://*/docs/*"))


class ParseRules(unittest.TestCase):
    def test_reads_every_key(self):
        rules = parse_rules(
            {
                "group": [
                    {
                        "title": "t",
                        "urls": ["a*"],
                        "color": "red",
                        "collapsed": True,
                    }
                ]
            }
        )
        self.assertEqual(
            rules,
            (Rule(title="t", urls=("a*",), color="red", collapsed=True),),
        )

    def test_no_rules_is_empty(self):
        self.assertEqual(parse_rules({}), ())

    def test_says_what_is_wrong(self):
        cases = {
            "needs a title": {"urls": ["a"]},
            "urls must be a list": {"title": "t", "urls": "a*"},
            "color must be one of": {
                "title": "t",
                "urls": ["a"],
                "color": "teal",
            },
            "unknown key": {"title": "t", "urls": ["a"], "colour": "red"},
            "collapsed is true or false": {
                "title": "t",
                "urls": ["a"],
                "collapsed": "yes",
            },
        }
        for message, table in cases.items():
            with self.subTest(message), self.assertRaises(ValueError) as e:
                parse_rules({"group": [table]})
            self.assertIn(message, str(e.exception))


class PlanSteps(unittest.TestCase):
    def test_makes_a_group_per_rule(self):
        listing = make_listing(
            [
                make_tab(1, "http://127.0.0.1:2718/?file=a.py"),
                make_tab(2, "https://docs.python.org/3/"),
                make_tab(3, "http://127.0.0.1:2719/?file=b.py"),
                make_tab(4, "https://example.com/"),
            ]
        )
        self.assertEqual(
            plan_steps(listing, (NOTEBOOKS, DOCS)),
            (
                NewGroup(
                    tab_ids=(1, 3),
                    window_id=1,
                    title="notebooks",
                    color="blue",
                    collapsed=None,
                ),
                NewGroup(
                    tab_ids=(2,),
                    window_id=1,
                    title="docs",
                    color=None,
                    collapsed=None,
                ),
            ),
        )

    def test_joins_the_group_of_that_title_in_the_same_window(self):
        groups = [
            Group(
                id=10,
                window_id=1,
                title="notebooks",
                color="blue",
                collapsed=False,
            ),
            Group(
                id=20,
                window_id=2,
                title="notebooks",
                color="blue",
                collapsed=False,
            ),
        ]
        listing = make_listing(
            [
                make_tab(1, "http://127.0.0.1:2718/?file=a.py", group_id=10),
                make_tab(2, "http://127.0.0.1:2718/?file=b.py"),
                make_tab(3, "http://127.0.0.1:2718/?file=c.py", window_id=2),
            ],
            groups,
            windows=(1, 2),
        )
        self.assertEqual(
            plan_steps(listing, (NOTEBOOKS,)),
            (
                JoinGroup(tab_ids=(2,), group_id=10),
                JoinGroup(tab_ids=(3,), group_id=20),
            ),
        )

    def test_leaves_pinned_and_grouped_tabs(self):
        mine = Group(
            id=7, window_id=1, title="mine", color="red", collapsed=False
        )
        listing = make_listing(
            [
                make_tab(1, "http://127.0.0.1:2718/?file=a.py", pinned=True),
                make_tab(2, "http://127.0.0.1:2718/?file=b.py", group_id=7),
            ],
            [mine],
        )
        self.assertEqual(plan_steps(listing, (NOTEBOOKS,)), ())

    def test_first_matching_rule_wins(self):
        everything = Rule(title="all", urls=("*",))
        listing = make_listing([make_tab(1, "https://docs.python.org/")])
        (step,) = plan_steps(listing, (DOCS, everything))
        self.assertEqual(step.title, "docs")

    def test_recolors_a_group_whose_color_drifted(self):
        group = Group(
            id=10, window_id=1, title="notebooks", color="red", collapsed=False
        )
        listing = make_listing([], [group])
        self.assertEqual(
            plan_steps(listing, (NOTEBOOKS,)),
            (Recolor(group_id=10, color="blue"),),
        )


class StepRequest(unittest.TestCase):
    def test_new_group_names_its_window_and_looks(self):
        step = NewGroup(
            tab_ids=(1, 2), window_id=3, title="t", color="red", collapsed=None
        )
        self.assertEqual(
            step_request(step),
            (
                "group",
                {
                    "tabIds": [1, 2],
                    "windowId": 3,
                    "title": "t",
                    "color": "red",
                    "collapsed": None,
                },
            ),
        )


class PlanTabSteps(unittest.TestCase):
    def test_moves_only_the_tabs_named(self):
        tabs = [
            make_tab(1, "http://127.0.0.1:2718/?file=a.py"),
            make_tab(2, "http://127.0.0.1:2718/?file=b.py"),
        ]
        steps = plan_tab_steps(make_listing(tabs), (NOTEBOOKS,), {2})
        self.assertEqual(
            steps,
            (
                NewGroup(
                    tab_ids=(2,),
                    window_id=1,
                    title="notebooks",
                    color="blue",
                    collapsed=None,
                ),
            ),
        )

    def test_joins_the_group_without_recoloring_it(self):
        group = Group(
            id=9, window_id=1, title="notebooks", color="red", collapsed=False
        )
        tabs = [make_tab(1, "http://127.0.0.1:2718/?file=a.py")]
        steps = plan_tab_steps(
            make_listing(tabs, groups=[group]), (NOTEBOOKS,), {1}
        )
        self.assertEqual(steps, (JoinGroup(tab_ids=(1,), group_id=9),))

    def test_nothing_for_a_tab_no_rule_matches(self):
        tabs = [make_tab(1, "https://example.org/")]
        self.assertEqual(
            plan_tab_steps(make_listing(tabs), (NOTEBOOKS,), {1}), ()
        )


if __name__ == "__main__":
    unittest.main()
