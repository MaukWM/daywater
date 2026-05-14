"""Session management: directory layout, state machine, persistence."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from src.logging import logger

SESSIONS_ROOT = Path("/app/sessions") if Path("/app/sessions").exists() else Path("./sessions")
ISO_CACHE_ROOT = Path("/app/cache/isos") if Path("/app/cache").exists() else Path("./cache/isos")


class SessionState(StrEnum):
    CREATED = "created"
    ISO_UPLOADED = "iso_uploaded"
    SAVESTATE_UPLOADED = "savestate_uploaded"
    FRAME_READY = "frame_ready"
    MASK_READY = "mask_ready"
    READY = "ready"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


# Valid state transitions. Survey runs independently (tracked by survey_complete flag).
_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.CREATED: {SessionState.ISO_UPLOADED},
    SessionState.ISO_UPLOADED: {SessionState.SAVESTATE_UPLOADED},
    SessionState.SAVESTATE_UPLOADED: {SessionState.FRAME_READY},
    SessionState.FRAME_READY: {SessionState.MASK_READY},
    SessionState.MASK_READY: {SessionState.READY},
    SessionState.READY: {SessionState.RUNNING},
    SessionState.RUNNING: {SessionState.DONE, SessionState.FAILED},
    SessionState.DONE: {SessionState.READY},
    SessionState.FAILED: {SessionState.READY},
}


@dataclass
class SessionConfig:
    """Persisted session metadata."""

    session_id: str
    state: SessionState = SessionState.CREATED
    created_at: float = field(default_factory=time.time)

    # Set after ISO upload.
    game_id: str = ""
    iso_sha1: str = ""
    iso_size: int = 0

    # Survey progress.
    survey_binaries_total: int = 0
    survey_binaries_done: int = 0
    survey_complete: bool = False
    inventory_text: str = ""

    # Agent config (editable before run).
    run_seconds: int = 10
    verify_budget: int = 8
    hud_min_mean: float = 5.0
    preserve_max_mean: float = 6.0
    hint: str = "Remove all HUD elements marked in the mask."

    # Result (set after run).
    result_verdict: str = ""
    result_gecko: str = ""
    result_hud_mean: float = 0.0
    result_preserve_mean: float = 0.0


class Session:
    """Manages one session's directory and state."""

    def __init__(self, root: Path, config: SessionConfig) -> None:
        self.root = root
        self.config = config

    @property
    def session_id(self) -> str:
        return self.config.session_id

    @property
    def state(self) -> SessionState:
        return self.config.state

    # Well-known file paths within the session directory.
    @property
    def iso_path(self) -> Path:
        return self.root / "iso.iso"

    @property
    def savestate_path(self) -> Path:
        return self.root / "savestate.sav"

    @property
    def reference_path(self) -> Path:
        return self.root / "reference.png"

    @property
    def mask_path(self) -> Path:
        return self.root / "mask.png"

    @property
    def config_path(self) -> Path:
        return self.root / "config.json"

    @property
    def events_path(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def result_gecko_path(self) -> Path:
        return self.root / "result.gecko"

    @property
    def result_frame_path(self) -> Path:
        return self.root / "result_frame.png"

    def transition(self, new_state: SessionState) -> None:
        """Advance the state machine. Raises ValueError on illegal transition."""
        allowed = _TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise ValueError(f"cannot transition {self.state} -> {new_state}")
        logger.info("session_transition", session=self.session_id, old=self.state, new=new_state)
        self.config.state = new_state
        self.save()

    def save(self) -> None:
        """Persist config to disk."""
        self.config_path.write_text(json.dumps(asdict(self.config), indent=2))

    def append_event(self, event: dict[str, Any]) -> None:
        """Append a JSON line to the session's event log."""
        event.setdefault("ts", time.time())
        with self.events_path.open("a") as f:
            f.write(json.dumps(event) + "\n")

    def status_dict(self) -> dict[str, Any]:
        """Return a status summary suitable for the API."""
        d = asdict(self.config)
        d["has_savestate"] = self.savestate_path.exists()
        d["has_reference"] = self.reference_path.exists()
        d["has_mask"] = self.mask_path.exists()
        return d


class SessionStore:
    """Manages all sessions on disk."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or SESSIONS_ROOT
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self) -> Session:
        sid = uuid.uuid4().hex[:12]
        session_dir = self.root / sid
        session_dir.mkdir(parents=True)
        config = SessionConfig(session_id=sid)
        session = Session(session_dir, config)
        session.save()
        logger.info("session_created", session=sid)
        return session

    def get(self, session_id: str) -> Session | None:
        session_dir = self.root / session_id
        config_path = session_dir / "config.json"
        if not config_path.exists():
            return None
        raw = json.loads(config_path.read_text())
        config = SessionConfig(**raw)
        return Session(session_dir, config)

    def list_sessions(self) -> list[SessionConfig]:
        sessions = []
        for d in sorted(self.root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            cfg_path = d / "config.json"
            if cfg_path.exists():
                raw = json.loads(cfg_path.read_text())
                sessions.append(SessionConfig(**raw))
        return sessions
