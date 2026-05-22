"""Centralized path resolution for Docker (/app/) vs local (./.) environments.

Every path that differs between Docker and local dev should be resolved
through this module. The detection is done once at import time: if
``/app/sessions`` exists we're in the container, otherwise local.
"""

from __future__ import annotations

from pathlib import Path

_IN_CONTAINER = Path("/app/sessions").exists()
_ROOT = Path("/app") if _IN_CONTAINER else Path(".")


def sessions_root() -> Path:
    """Project session storage (project configs, savestates, tasks)."""
    return _ROOT / "sessions"


def cache_root() -> Path:
    """Top-level cache (extracted ISOs, Ghidra analysis, etc.)."""
    return _ROOT / "cache"


def binaries_cache() -> Path:
    """Ghidra-analyzed binary cache (``cache/binaries/<sha>/``)."""
    return cache_root() / "binaries"


def iso_cache_root() -> Path:
    """ISO image cache (``cache/isos/``)."""
    return cache_root() / "isos"


def logs_root() -> Path:
    """Inspect AI and application logs."""
    return _ROOT / "logs"


def samples_root() -> Path:
    """Sample binaries for Ghidra smoke tests."""
    return _ROOT / "samples"
