"""Risk tiers decide how a Work Order is confirmed: notice, veto window, or a
blocking review. A misclassified call either nags the human or slips past them."""
import pytest

from CoScientist.hitl.work_order_risk import (
    SideEffectKind,
    Tier,
    classify_call,
    order_tier,
    tool_tier,
)


def test_known_tools_have_their_tier_and_unknown_tools_count_as_compute():
    assert tool_tier("tavily_search") == Tier.READ
    assert tool_tier("execute_bash") == Tier.COMPUTE
    assert tool_tier("install_package") == Tier.SIDE_EFFECT
    # Nobody classified it: guessing "read" would let it through unseen.
    assert tool_tier("some_new_mcp_tool") == Tier.COMPUTE


@pytest.mark.parametrize("command, kind", [
    ("git push origin main", SideEffectKind.GIT_WRITE),
    ("cd repo && git commit -m 'x'", SideEffectKind.GIT_WRITE),
    ("pip install rdkit", SideEffectKind.PACKAGE_INSTALL),
    ("uv pip install -r requirements.txt", SideEffectKind.PACKAGE_INSTALL),
    ("rm -rf data/", SideEffectKind.FILE_DELETE),
    ("wget https://example.org/chembl.sdf.gz", SideEffectKind.NETWORK_DOWNLOAD),
    ("huggingface-cli download org/dataset", SideEffectKind.NETWORK_DOWNLOAD),
    ("nohup python train.py > log.txt", SideEffectKind.LONG_JOB),
    ("python train.py &", SideEffectKind.LONG_JOB),
])
def test_bash_commands_with_effects_beyond_the_sandbox_are_side_effects(command, kind):
    assert classify_call("execute_bash", {"command": command}) == (Tier.SIDE_EFFECT, kind)


@pytest.mark.parametrize("command", [
    "python analyze.py 2>&1",
    "ls -la && cat MANIFEST.md",
    "grep -r IC50 data/",
])
def test_ordinary_bash_is_compute(command):
    assert classify_call("execute_bash", {"command": command}) == (Tier.COMPUTE, None)


def test_a_tool_that_is_a_side_effect_by_nature_ignores_its_arguments():
    assert classify_call("install_package", {"name": "numpy"}) == (
        Tier.SIDE_EFFECT, SideEffectKind.PACKAGE_INSTALL,
    )


def test_order_tier_is_its_riskiest_element():
    assert order_tier(["tavily_search", "search_papers"], []) == Tier.READ
    assert order_tier(["tavily_search", "execute_bash"], []) == Tier.COMPUTE
    assert order_tier(["tavily_search"], [SideEffectKind.NETWORK_DOWNLOAD]) == Tier.SIDE_EFFECT
    assert order_tier([], []) == Tier.READ
