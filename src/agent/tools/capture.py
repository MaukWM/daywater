"""Screenshot capture tool and frame content helper.

The ``_capture_frame_content`` helper is shared by both ``capture_screenshot``
(this module) and ``apply_gecko_code`` (gecko/live.py).
"""

from __future__ import annotations

import base64
from typing import Any

from inspect_ai.tool import Tool, tool

from src.core.dolphin.session_ref import SessionRef
from src.core.logging import logger


def _capture_frame_content(session_ref: SessionRef) -> Any | None:
    """Grab the latest dumped frame from Dolphin as a ContentImage.

    Re-encodes through Pillow to fix truncated/corrupt PNGs that Dolphin's
    Software renderer can produce (frames written mid-render).
    """
    import io

    from inspect_ai.model import ContentImage
    from PIL import Image

    session = session_ref.session
    frames_dir = session.user_dir / "Dump" / "Frames"
    frames = sorted(frames_dir.glob("*.png"))
    if not frames:
        return None
    try:
        img = Image.open(frames[-1])
        img.load()  # force full decode — catches truncated files
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return ContentImage(image=f"data:image/png;base64,{b64}")
    except Exception:
        logger.warning("frame_capture_failed", path=str(frames[-1]))
        return None


@tool
def capture_screenshot(session_ref: SessionRef) -> Tool:
    """Build a screenshot capture tool bound to a SessionRef."""

    async def execute() -> list[Any] | str:
        """Capture the current Dolphin frame as an image.

        Returns a screenshot of the game's current visual state. Use this
        to visually inspect what's happening after applying codes or input.
        """
        frame = _capture_frame_content(session_ref)
        if frame is None:
            return "No frames available — Dolphin may not be rendering."
        from inspect_ai.model import ContentText

        return [ContentText(text="Screenshot captured."), frame]

    return execute
