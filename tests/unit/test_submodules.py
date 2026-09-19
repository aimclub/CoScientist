"""Every submodule .gitmodules declares must still be in the tree.

68dcd4d ("Hypothesis subsystem a2a mcp", #326) deleted the gitlink for
``infrastructure/openchemie`` and left the ``.gitmodules`` entry, the README
entry and the OCR pipeline that calls the service all in place. Its commit
message does not mention the submodule at all — it mentions removing ``.idea``
— so it went out as a side effect of a cleanup.

Nothing failed: ``git submodule update --init`` simply had nothing to do, and
a fresh clone came up without the service while still advertising it. The
mismatch is only visible if you look for it, which is what this does.
"""
from __future__ import annotations

import configparser
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GITMODULES = ROOT / ".gitmodules"


def _declared_paths() -> list[str]:
    if not GITMODULES.exists():
        return []
    parser = configparser.ConfigParser()
    # .gitmodules is INI with tab-indented keys; configparser handles it once
    # the leading whitespace is gone.
    parser.read_string(
        "\n".join(line.strip() for line in GITMODULES.read_text(encoding="utf-8").splitlines())
    )
    return [parser[s]["path"] for s in parser.sections() if parser.has_option(s, "path")]


def _gitlinks() -> set[str]:
    """Paths git records as submodules (mode 160000) in this checkout."""
    try:
        done = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--stage"],
            capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"git is not usable here: {exc}")
    if done.returncode != 0:
        pytest.skip("not a git checkout")
    return {
        line.split("\t", 1)[1]
        for line in done.stdout.splitlines()
        if line.startswith("160000 ") and "\t" in line
    }


@pytest.mark.parametrize("path", _declared_paths() or [pytest.param(None, marks=pytest.mark.skip)])
def test_a_declared_submodule_is_still_in_the_tree(path: str):
    assert path in _gitlinks(), (
        f".gitmodules declares {path!r} but nothing in the tree is a submodule "
        "there — either the gitlink was dropped by accident, or the declaration "
        "should have gone with it"
    )
