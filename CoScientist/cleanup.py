"""Best-effort resource cleanup helpers for terminal A2A paths."""

import asyncio
import logging
from collections.abc import Callable


logger = logging.getLogger(__name__)


def has_uploaded_papers(session: object | None) -> bool:
    """Return whether a session owns S3 objects that require cleanup."""
    state = getattr(session, "state", None)
    return isinstance(state, dict) and bool(state.get("uploaded_paper_s3_keys"))


async def run_bounded_cleanup(
    cleanup: Callable[[str, str], None],
    user_id: str,
    session_id: str,
    timeout_seconds: float,
) -> None:
    """Run blocking cleanup without delaying a terminal A2A response forever."""
    try:
        await asyncio.wait_for(
            asyncio.to_thread(cleanup, user_id, session_id),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Timed out cleaning uploaded papers for session %s after %.1fs; "
            "continuing A2A finalization",
            session_id,
            timeout_seconds,
        )
    except Exception as exc:
        logger.warning(
            "Failed to clean uploaded papers for session %s: %s", session_id, exc
        )
