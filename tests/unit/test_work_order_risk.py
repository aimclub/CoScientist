"""Risk tiers decide how a Work Order is confirmed: notice, veto window, or a
blocking review. A misclassified call either nags the human or slips past them."""
from CoScientist.hitl.work_order_risk import (
    SideEffectKind,
    Tier,
    order_tier,
    tool_tier,
)


def test_known_tools_have_their_tier_and_unknown_tools_count_as_compute():
    assert tool_tier("tavily_search") == Tier.READ
    assert tool_tier("execute_bash") == Tier.COMPUTE
    assert tool_tier("install_package") == Tier.SIDE_EFFECT
    # Nobody classified it: guessing "read" would let it through unseen.
    assert tool_tier("some_new_mcp_tool") == Tier.COMPUTE


def test_order_tier_is_its_riskiest_element():
    assert order_tier(["tavily_search", "search_papers"], []) == Tier.READ
    assert order_tier(["tavily_search", "execute_bash"], []) == Tier.COMPUTE
    assert order_tier(["tavily_search"], [SideEffectKind.NETWORK_DOWNLOAD]) == Tier.SIDE_EFFECT
    assert order_tier([], []) == Tier.READ
