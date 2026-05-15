"""SSE event streaming from project/task event logs."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncGenerator, Protocol


class Streamable(Protocol):
    """Anything with events_path and config_path (Project or Task)."""

    @property
    def events_path(self) -> Path: ...

    @property
    def config_path(self) -> Path: ...


async def stream_events(entity: Streamable) -> AsyncGenerator[str, None]:
    """Yield SSE-formatted events by tailing an entity's events.jsonl.

    Works with both Project (survey events) and Task (agent events).
    Starts from the beginning of the file and tails until the entity
    reaches a terminal state (done/failed) or the client disconnects.
    """
    events_path = entity.events_path
    config_path = entity.config_path
    offset = 0

    while True:
        # Re-read state from disk to catch transitions.
        try:
            config_text = config_path.read_text()
            state = json.loads(config_text).get("state", "")
        except (FileNotFoundError, json.JSONDecodeError):
            state = ""

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
