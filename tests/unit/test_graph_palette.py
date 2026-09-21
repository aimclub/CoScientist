"""Colour has to answer one question per channel, or it answers none.

The research canvas encodes three things at once: the card's colour is WHAT the
node is, the status word's colour is WHERE the claim stands, and the link's
colour is HOW two cards relate. Each of the ways that breaks is invisible —
nothing throws, nothing looks wrong on a small graph, and the reader simply
stops being able to tell two kinds of card apart:

* a type missing from ``R_KIND`` does not lose its colour, it inherits the
  STATUS colour, which is how ``Hypothesis`` (deliberately left out so it could
  carry its verdict) came out amber next to an orange ``Evidence``;
* two types sharing a hue look like one type — tool, dataset and code were all
  ``#a9682a``, and conclusion, report and publication all ``#fb923c``;
* a type taking green or red makes an ordinary card read as a verdict.

These are cheap checks against the server's own list of node types, so a new
type cannot be added without being given a colour.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from CoScientist.graph.research.schema import NODE_TYPES

PAGE = (
    Path(__file__).resolve().parents[2]
    / "CoScientist" / "web" / "templates" / "graph.html"
)

#: The two colours the verdict owns, as the page's :root declares them.
GOOD, CRIT = "#22c55e", "#ef4444"


@pytest.fixture(scope="module")
def page() -> str:
    return PAGE.read_text(encoding="utf-8")


def _table(page: str, name: str) -> dict[str, str]:
    """The `kind: "#rrggbb"` pairs of one const table."""
    block = re.search(r"const " + name + r" = \{(.*?)\n    \};", page, re.S)
    assert block, f"the page must still declare {name}"
    return dict(re.findall(r"(\w+):\s*\"(#[0-9a-fA-F]{6})\"", block.group(1)))


def test_every_node_type_the_server_can_write_has_a_colour(page):
    kinds = _table(page, "R_KIND")
    want = {name.lower() for name in NODE_TYPES}
    assert want - set(kinds) == set(), sorted(want - set(kinds))
    # And nothing extra: a stale key is a colour nobody can see, and it hides
    # the fact that the type it was for has gone.
    assert set(kinds) - want == set(), sorted(set(kinds) - want)


def test_no_two_types_share_a_colour(page):
    kinds = _table(page, "R_KIND")
    seen: dict[str, list[str]] = {}
    for kind, colour in kinds.items():
        seen.setdefault(colour.lower(), []).append(kind)
    clashes = {c: k for c, k in seen.items() if len(k) > 1}
    assert not clashes, clashes


def test_the_two_cards_a_reader_must_tell_apart_are_not_alike(page):
    """The complaint that started this: a claim and a measurement."""
    kinds = _table(page, "R_KIND")
    assert "hypothesis" in kinds, "the central claim cannot borrow the verdict colour"
    assert kinds["hypothesis"] != kinds["evidence"]


def test_green_and_red_belong_to_the_verdict_alone(page):
    kinds = _table(page, "R_KIND")
    taken = {c.lower() for c in kinds.values()}
    assert GOOD not in taken, "a green card reads as a confirmed one"
    assert CRIT not in taken, "a red card reads as a refuted one"


def test_a_settled_claim_is_green_a_rejected_one_red_and_the_rest_neutral(page):
    good = re.search(r"const STATUS_GOOD = new Set\(\[(.*?)\]\)", page, re.S)
    bad = re.search(r"const STATUS_BAD = new Set\(\[(.*?)\]\)", page, re.S)
    assert good and bad, "the page must still declare the two verdict sets"
    positive = set(re.findall(r'"(\w+)"', good.group(1)))
    negative = set(re.findall(r'"(\w+)"', bad.group(1)))
    assert {"confirmed", "validated", "met", "approved"} <= positive
    assert {"refuted", "rejected", "failed"} <= negative
    assert not positive & negative
    # Everything else is neither, and says so in neutral ink rather than in a
    # third colour: a method still running is not bad news.
    assert re.search(r"statusInk = st => STATUS_GOOD\.has\(st\) \? GOOD\s*"
                     r":\s*STATUS_BAD\.has\(st\) \? CRIT : INK2", page)
    for status in ("inconclusive", "postponed", "under_verification", "planned"):
        assert f'"{status}"' not in good.group(1)
        assert f'"{status}"' not in bad.group(1)


def test_the_status_word_is_the_one_thing_on_the_card_wearing_that_colour(page):
    """vis styles four label classes; `boldital` is the only one this card does
    not already spend, so the status word is wrapped in <b><i> and that class
    is given the verdict colour."""
    assert 'boldital: { color: statusInk(n.status)' in page
    assert 'mod: "bold"' in page, "a status word is bold, not italic"
    assert '"<b>" + head + " · </b><b><i>" + visSafe(sw) + "</i></b>"' in page


def test_an_untyped_link_is_not_three_stops_off_the_background(page):
    """The canvas is #14161a, so a legible link is a light one. #4a5160 and
    #4b5563 were the two greys a reader could not follow across a study."""
    for dim in ('"#4a5160"', '"#4b5563"', '"#aeb6c2"', '"#6b7280", size: 11'):
        assert dim not in page, dim
    assert 'const EDGE_NEUTRAL = "#cbd5e1"' in page


def test_an_edge_label_is_escaped_before_it_is_made_bold(page):
    """Enabling the html parser on a label means the same rule as the cards:
    a '<' or a stray '&' in an agent-written reason must not reach it."""
    assert re.search(r"edgeLabel = v => \{ const e = visSafe\(", page)
    assert 'return e ? "<b>" + e + "</b>" : ""' in page
    # Every research edge label goes through it, including the one that
    # interpolates a model-written reason.
    assert "edge.label = edgeLabel(t('graph.edge.supersedes.'" in page
    assert "(research ? edgeLabel(rlabel) : rlabel)" in page
