"""Typed per-Sample agent state, backed by Inspect AI's ``store()``.

All per-sample state is accessed through ``SampleStore``. Tools and the
scorer import ``sample_store`` (module-level instance) or the convenience
functions below — no raw magic-string keys leak outside this module.

For MCP / non-Inspect backends, replace ``SampleStore._store()`` with a
dict-backed alternative; the rest of the API stays the same.
"""

from __future__ import annotations

from pathlib import Path

from inspect_ai.util import store

from src.ghidra.analyze import cache_dir_for_sha1


class SampleStore:
    """Typed wrapper around Inspect AI's per-sample key-value store."""

    # Key constants — private to this class.
    _BUDGET_KEY = "daywater_run_gecko_used"
    _LAST_PASS_KEY = "daywater_last_pass_gecko"
    _CURRENT_BINARY_SHA1_KEY = "daywater_current_binary_sha1"
    _KNOWN_BINARIES_KEY = "daywater_known_binaries"

    @staticmethod
    def _store():  # type: ignore[no-untyped-def]
        """Return the backing store. Override for non-Inspect backends."""
        return store()

    # ── Gecko budget ──────────────────────────────────────────────────── #

    def gecko_budget_used(self) -> int:
        """Number of ``run_gecko`` calls consumed so far."""
        return int(self._store().get(self._BUDGET_KEY, 0))

    def increment_gecko_budget(self) -> int:
        """Consume one budget slot. Returns the new call index (1-based)."""
        used = self.gecko_budget_used()
        self._store().set(self._BUDGET_KEY, used + 1)
        return used + 1

    # ── Last passing gecko code ───────────────────────────────────────── #

    def last_pass_gecko(self) -> str | None:
        """Last gecko_text that earned a PASS, or None."""
        val = self._store().get(self._LAST_PASS_KEY)
        if isinstance(val, str) and val.strip():
            return val
        return None

    def set_last_pass_gecko(self, gecko_text: str) -> None:
        """Stash the most recent passing gecko code for scorer fallback."""
        self._store().set(self._LAST_PASS_KEY, gecko_text)

    # ── Active binary ─────────────────────────────────────────────────── #

    def current_binary_sha1(self) -> str | None:
        """SHA-1 of the binary the agent is currently exploring, or None."""
        sha1 = self._store().get(self._CURRENT_BINARY_SHA1_KEY)
        if isinstance(sha1, str) and sha1:
            return sha1
        return None

    def set_current_binary(self, sha1: str, source_path: Path | None = None) -> None:
        """Switch the active binary the read tools target."""
        s = self._store()
        s.set(self._CURRENT_BINARY_SHA1_KEY, sha1)
        if source_path is not None:
            known = dict(s.get(self._KNOWN_BINARIES_KEY, {}) or {})
            known[sha1] = str(source_path)
            s.set(self._KNOWN_BINARIES_KEY, known)

    def current_cache_dir(self) -> Path | None:
        """Cache dir for the selected binary, or None if none selected."""
        sha1 = self.current_binary_sha1()
        if sha1:
            return cache_dir_for_sha1(sha1)
        return None

    def known_binaries(self) -> dict[str, str]:
        """Snapshot of {sha1: source_path} for binaries analyzed this session."""
        raw: dict[str, str] = self._store().get(self._KNOWN_BINARIES_KEY, {}) or {}
        return {str(k): str(v) for k, v in raw.items()}


# Module-level instance — all callers share this.
sample_store = SampleStore()


# ── Convenience wrappers (preserve existing call sites) ───────────────── #


def set_current_binary(sha1: str, source_path: Path | None = None) -> None:
    """Switch the active binary the read tools target."""
    sample_store.set_current_binary(sha1, source_path)


def current_cache_dir() -> Path | None:
    """Cache dir for the binary the agent has selected, or None."""
    return sample_store.current_cache_dir()


def known_binaries() -> dict[str, str]:
    """Snapshot of binaries the agent has analyzed this session."""
    return sample_store.known_binaries()


NO_BINARY_SELECTED_MSG = (
    "No binary selected yet. Review the binary inventory in the initial "
    "task description and call `switch_binary(<sha1>)` to pick one before "
    "using the static-analysis tools."
)
