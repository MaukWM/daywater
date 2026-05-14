"""SSE event streaming from session event logs."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncGenerator

from src.web.sessions import Session


async def stream_events(session: Session) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted events by tailing the session's events.jsonl.

    Starts from the beginning of the file and tails until the session
    reaches a terminal state (done/failed) or the client disconnects.
    """
    events_path = session.events_path
    offset = 0

    while True:
        # Re-read session state from disk to catch transitions.
        config_text = session.config_path.read_text()
        state = json.loads(config_text).get("state", "")

        if events_path.exists():
            content = events_path.read_text()
            lines = content.split("\n")
            new_lines = lines[offset:]
            for line in new_lines:
                line = line.strip()
                if line:
                    yield f"data: {line}\n\n"
            offset = len(lines)

        # Send a heartbeat to keep the connection alive.
        yield f"data: {json.dumps({'t': 'heartbeat', 'state': state})}\n\n"

        if state in ("done", "failed"):
            yield f"data: {json.dumps({'t': 'stream_end', 'state': state})}\n\n"
            break

        await asyncio.sleep(1)
