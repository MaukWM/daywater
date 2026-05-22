"""Mutable proxy to a :class:`DolphinSession`.

Attribute access is forwarded to the underlying session so existing tools
(which expect ``DolphinSession``) work without changes.  The noclip task
calls :meth:`swap` when it reboots Dolphin with new Gecko codes.
"""

from __future__ import annotations

from typing import Any

from src.core.dolphin.session import DolphinSession


class SessionRef:
    """Mutable proxy to a :class:`DolphinSession`.

    Attribute access is forwarded to the underlying session so existing tools
    (which expect ``DolphinSession``) work without changes.  The noclip task
    calls :meth:`swap` when it reboots Dolphin with new Gecko codes.
    """

    def __init__(self, session: DolphinSession) -> None:
        # Store in object __dict__ directly to avoid __getattr__ recursion.
        object.__setattr__(self, "_session", session)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_session"), name)

    @property
    def session(self) -> DolphinSession:
        return object.__getattribute__(self, "_session")

    def swap(self, new_session: DolphinSession) -> None:
        object.__setattr__(self, "_session", new_session)
