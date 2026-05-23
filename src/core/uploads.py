"""File upload validation and persistence."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from PIL import Image

from src.core.dolphin.runner import read_game_id
from src.core.logging import logger
from src.core.sessions import ISO_CACHE_ROOT, Project, Savestate, Task, TaskState

# Limits.
MAX_ISO_SIZE = 10_000_000_000  # 10 GB (GC ~4.4 GB; Wii dual-layer ~8.5 GB)
MAX_SAVESTATE_SIZE = 1_000_000_000  # 1 GB (Dolphin savestates typically <100 MB)
MAX_SCREENSHOT_SIZE = 100_000_000  # 100 MB (no upload route currently; safety net)

FRAME_SIZE = (640, 480)


def _sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def save_iso(project: Project, tmp_path: Path, size: int) -> dict[str, object]:
    """Validate and persist an uploaded ISO to the project.

    The ISO is SHA-1 deduplicated: if the same ISO was uploaded in a prior
    project, we symlink to the cached copy.
    """
    if size > MAX_ISO_SIZE:
        raise ValueError(f"ISO too large ({size:,} bytes, max {MAX_ISO_SIZE:,})")

    game_id = read_game_id(tmp_path)
    if not game_id or len(game_id) != 6:
        raise ValueError(f"Cannot read game ID from ISO header (got {game_id!r})")

    sha1 = _sha1_file(tmp_path)

    # Dedup: cache by SHA-1.
    ISO_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    cached = ISO_CACHE_ROOT / f"{sha1}.iso"
    if not cached.exists():
        shutil.move(str(tmp_path), str(cached))
        logger.info("iso_cached", sha1=sha1, size=size)
    else:
        tmp_path.unlink(missing_ok=True)
        logger.info("iso_cache_hit", sha1=sha1)

    # Symlink from project dir.
    project.iso_path.unlink(missing_ok=True)
    project.iso_path.symlink_to(cached)

    project.config.game_id = game_id
    project.config.iso_sha1 = sha1
    project.config.iso_size = size
    project.save()

    return {"sha1": sha1, "game_id": game_id, "size": size}


def save_savestate_to_project(
    project: Project, tmp_path: Path, size: int, name: str = "",
) -> Savestate:
    """Validate and persist an uploaded savestate to the project."""
    if size > MAX_SAVESTATE_SIZE:
        raise ValueError(f"Savestate too large ({size:,} bytes, max {MAX_SAVESTATE_SIZE:,})")

    ss = project.create_savestate(name=name)
    shutil.move(str(tmp_path), str(ss.savestate_path))
    logger.info("savestate_uploaded", project=project.project_id, savestate=ss.savestate_id, size=size)
    return ss


def save_screenshot_to_savestate(ss: Savestate, frame_path: Path) -> None:
    """Normalize and cache a rendered frame as the savestate's screenshot."""
    img = Image.open(frame_path)
    if img.size != FRAME_SIZE:
        img = img.resize(FRAME_SIZE, Image.LANCZOS)
    img.convert("RGB").save(ss.screenshot_path, "PNG")
    logger.info("screenshot_saved", savestate=ss.savestate_id)


def save_screenshot(task: Task, tmp_path: Path, size: int) -> dict[str, object]:
    """Validate and persist an uploaded screenshot as the reference frame."""
    if size > MAX_SCREENSHOT_SIZE:
        raise ValueError(f"Screenshot too large ({size:,} bytes, max {MAX_SCREENSHOT_SIZE:,})")

    img = Image.open(tmp_path)
    original_size = img.size

    # Normalize to 640x480.
    if img.size != FRAME_SIZE:
        img = img.resize(FRAME_SIZE, Image.LANCZOS)

    img.convert("RGB").save(task.reference_path, "PNG")
    tmp_path.unlink(missing_ok=True)

    task.transition(TaskState.FRAME_READY)
    return {"ok": True, "original_size": list(original_size), "normalized_to": list(FRAME_SIZE)}


def save_reference_frame(task: Task, frame_path: Path) -> None:
    """Copy a probe-captured frame as the task's reference image."""
    img = Image.open(frame_path)
    if img.size != FRAME_SIZE:
        img = img.resize(FRAME_SIZE, Image.LANCZOS)
    img.convert("RGB").save(task.reference_path, "PNG")
    task.transition(TaskState.FRAME_READY)
