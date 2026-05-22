"""Live-session Gecko code application with crash recovery.

Tools: apply_gecko_code.
Helpers: _teardown_session, _teardown_session_raw, _rollback_after_crash.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from inspect_ai.tool import Tool, tool

from src.agent.tools.capture import _capture_frame_content
from src.dolphin.debugger import DolphinDiedDuringBoot, GDBError, _read_log_tail
from src.dolphin.session import DolphinSession
from src.dolphin.session_ref import SessionRef
from src.logging import logger


@tool
def apply_gecko_code(
    session_ref: SessionRef,
    iso_path: Path,
    savestate_path: Path,
    gdb_port: int | None = None,
) -> Tool:
    """Build a tool that reboots Dolphin with a Gecko code applied."""

    async def execute(gecko_text: str) -> list[Any] | str:
        """Reboot Dolphin from the savestate with a Gecko code applied.

        This terminates the current Dolphin session and starts a new one
        with your Gecko code injected. All runtime tools (memory, input,
        position) will work on the new session. Returns a screenshot.

        Args:
            gecko_text: Gecko code text. Use $Name headers and hex-pair lines.
                Example: "$Noclip\\n042967F0 00000001"
        """
        from src.dolphin.gecko import parse_gecko

        codes = parse_gecko(gecko_text)
        if not codes:
            return "Error: no valid Gecko codes found. Use $Name header + hex lines."

        code_summary = ", ".join(f"${c.name} ({len(c.lines)} lines)" for c in codes)
        logger.info("apply_gecko_code", codes=code_summary)

        # Terminate old session
        _teardown_session(session_ref)

        # Boot new session with gecko codes
        try:
            session_cm = DolphinSession.start(
                iso=iso_path,
                savestate=savestate_path,
                gecko_codes=codes,
                pipe_input=True,
                gdb_port=gdb_port,
            )
            new_session = session_cm.__enter__()
        except (DolphinDiedDuringBoot, GDBError) as e:
            logger.warning("gecko_crash_on_boot", error=str(e)[:300])
            return _rollback_after_crash(
                session_ref, iso_path, savestate_path, gdb_port,
                code_summary=code_summary,
                dolphin_log_tail=str(e),
                crash_stage="gdb_connect",
            )

        object.__setattr__(new_session, "_gecko_cm", session_cm)

        if not new_session.wait_for_first_frame():
            rc = new_session.proc.poll()
            log_path = (new_session._tmp_root or new_session.user_dir) / "dolphin.log"
            log_tail = _read_log_tail(log_path)
            new_session.preserve_crash_artifacts()
            _teardown_session_raw(new_session, session_cm)

            crash_stage = "dolphin_boot_crash" if rc is not None else "no_frames_timeout"
            logger.warning("gecko_crash_no_frames", exit_code=rc)
            return _rollback_after_crash(
                session_ref, iso_path, savestate_path, gdb_port,
                code_summary=code_summary,
                dolphin_log_tail=log_tail,
                crash_stage=crash_stage,
                exit_code=rc,
            )

        session_ref.swap(new_session)
        time.sleep(2.0)

        frame = _capture_frame_content(session_ref)
        from inspect_ai.model import ContentText

        parts: list[Any] = [
            ContentText(
                text=f"Gecko codes applied: {code_summary}. "
                f"Dolphin rebooted from savestate. Game is running."
            ),
        ]
        if frame is not None:
            parts.append(frame)
        return parts

    return execute


def _teardown_session(session_ref: SessionRef) -> None:
    """Terminate the current session and its context manager."""
    session = session_ref.session
    cm = getattr(session, "_gecko_cm", None)
    _teardown_session_raw(session, cm)


def _teardown_session_raw(
    session: DolphinSession, cm: Any | None
) -> None:
    """Terminate a session + optional context manager, swallowing errors."""
    try:
        session.terminate()
        session.cleanup()
    except Exception:
        pass
    if cm is not None:
        try:
            cm.__exit__(None, None, None)
        except Exception:
            pass


def _rollback_after_crash(
    session_ref: SessionRef,
    iso_path: Path,
    savestate_path: Path,
    gdb_port: int | None,
    *,
    code_summary: str,
    dolphin_log_tail: str,
    crash_stage: str,
    exit_code: int | None = None,
) -> str:
    """Roll back to a clean Dolphin session (no gecko codes) after a crash."""
    rollback_status = "failed"
    try:
        clean_cm = DolphinSession.start(
            iso=iso_path,
            savestate=savestate_path,
            pipe_input=True,
            gdb_port=gdb_port,
        )
        clean_session = clean_cm.__enter__()
        object.__setattr__(clean_session, "_gecko_cm", clean_cm)
        if clean_session.wait_for_first_frame():
            session_ref.swap(clean_session)
            rollback_status = "ok — clean session restored (no gecko codes)"
        else:
            rollback_status = "partial — Dolphin booted but no frames rendered"
    except Exception as e:
        rollback_status = f"failed — could not restart Dolphin: {e}"
        logger.error("rollback_restart_failed", error=str(e)[:200])

    exit_line = f"  exit_code: {exit_code}\n" if exit_code is not None else ""
    log_block = "\n".join("    " + ln for ln in dolphin_log_tail.splitlines())
    return (
        f"GECKO_CRASH:\n"
        f"  codes: {code_summary}\n"
        f"  crashed_at_step: {crash_stage}\n"
        f"{exit_line}"
        f"  rollback: {rollback_status}\n"
        f"  dolphin_log_tail: |\n{log_block}\n\n"
        f"Your Gecko code crashed Dolphin. It has been removed and a clean "
        f"session restored. Review the log tail above, then revise your code."
    )
