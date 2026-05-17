"""Wind-down budget enforcement — wraps every tool with a budget warning.

When the agent has used 90% of its message budget (measured in tool calls),
every tool response gets the wind-down warning appended. The agent can't
miss it — every single tool it calls will tell it to save and submit.
"""

from __future__ import annotations

import functools
from typing import Any

from inspect_ai.tool import Tool
from inspect_ai.util import store

_CALL_COUNT_KEY = "spectre_tool_call_count"

WINDDOWN_WARNING = (
    "\n\n⚠️ BUDGET CRITICAL — You are almost out of messages. "
    "STOP all exploration. You MUST now:\n"
    "1. save_finding() for each discovery\n"
    "2. save_savestate_finding() for runtime addresses\n"
    "3. write_research(filename, content, summary) to document analysis\n"
    "4. submit() with a summary\n"
    "Any further exploratory calls are wasted. Save your work NOW."
)


def wrap_tools_with_winddown(tools: list[Tool], message_limit: int) -> list[Tool]:
    """Wrap every tool to append a wind-down warning near the message limit.

    Each tool call increments a shared counter. At 90% of the budget
    (in tool-call units), every tool response gets the warning appended.
    """
    # ~2 messages per tool call round (assistant + tool response)
    threshold = int(message_limit * 0.9 / 2)

    return [_wrap_one(t, threshold) for t in tools]


def _wrap_one(original: Tool, threshold: int) -> Tool:
    """Wrap a single tool to track calls and inject warnings."""

    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        s = store()
        count = int(s.get(_CALL_COUNT_KEY, 0)) + 1
        s.set(_CALL_COUNT_KEY, count)

        result = await original(*args, **kwargs)

        if count >= threshold:
            if isinstance(result, str):
                return result + WINDDOWN_WARNING
            elif isinstance(result, list):
                from inspect_ai.model import ContentText

                return [*result, ContentText(text=WINDDOWN_WARNING)]

        return result

    functools.update_wrapper(wrapped, original)
    # Preserve Inspect AI tool registry metadata
    for attr in ("__registry_info__", "__registry_params__"):
        if hasattr(original, attr):
            setattr(wrapped, attr, getattr(original, attr))

    return wrapped  # type: ignore[return-value]
