"""Dolphin frame capture with glitch retry.

Runs Dolphin with Gecko codes, captures frames, and retries on render
glitches. No imports from src.agent or src.api.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.core.dolphin import collect_dump, load_png_frames, read_game_id, run_dolphin
from src.core.dolphin.diff import has_render_glitch, load_image_rgb
from src.core.dolphin.runner import RunResult, write_user_dir

# Max retries when a captured frame has a render glitch (black bar).
MAX_GLITCH_RETRIES = 2


@dataclass
class DolphinRunOutcome:
    """Result of a Dolphin run attempt, with crash diagnostics."""

    image: Any | None  # RGB numpy array or None
    crashed: bool = False
    returncode: int = 0
    elapsed: float = 0.0
    run_seconds_budget: int = 0

    @property
    def crash_detail(self) -> str:
        """Human-readable crash description for agent-facing messages."""
        if not self.crashed:
            return ""
        if self.returncode != 0 and self.elapsed < self.run_seconds_budget * 0.5:
            return (
                f"Dolphin crashed (exit code {self.returncode}) after "
                f"{self.elapsed:.1f}s — the game never rendered a frame. "
                f"Your Gecko code likely corrupted execution at the hook site."
            )
        return (
            f"Dolphin produced no frames in {self.elapsed:.1f}s "
            f"(budget {self.run_seconds_budget}s, exit code {self.returncode}). "
            f"The game may have crashed or entered an infinite loop before rendering."
        )


def run_dolphin_with_retry(
    iso_path: Path,
    savestate_path: Path,
    codes: list,  # type: ignore[type-arg]
    run_seconds: int,
    max_retries: int = MAX_GLITCH_RETRIES,
) -> DolphinRunOutcome:
    """Run Dolphin and capture frames, retrying if render glitch detected.

    Returns a ``DolphinRunOutcome`` with the candidate frame (or None) and
    crash diagnostics.
    """
    from src.core.logging import logger

    last_result: RunResult | None = None
    for attempt in range(1 + max_retries):
        tmp_root = Path(tempfile.mkdtemp(prefix="daywater_web_tool_"))
        try:
            user_dir = tmp_root / "user"
            game_id = read_game_id(iso_path)
            write_user_dir(user_dir, game_id, codes)
            last_result = run_dolphin(
                user_dir=user_dir,
                iso=iso_path,
                log_path=tmp_root / "dolphin.log",
                savestate=savestate_path,
                run_seconds=run_seconds,
            )

            # Ensure no orphan process lingers (belt + suspenders)
            _kill_orphan_dolphin(user_dir)

            frames_dir = tmp_root / "frames"
            collect_dump(user_dir, frames_dir)
            frames = load_png_frames(frames_dir)

            if not frames:
                logger.info(
                    "no_frames",
                    attempt=attempt + 1,
                    rc=last_result.returncode,
                    elapsed=round(last_result.elapsed_seconds, 1),
                    early_exit=last_result.elapsed_seconds < run_seconds * 0.8,
                )
                if attempt < max_retries:
                    continue
                return DolphinRunOutcome(
                    image=None,
                    crashed=True,
                    returncode=last_result.returncode,
                    elapsed=last_result.elapsed_seconds,
                    run_seconds_budget=run_seconds,
                )

            candidate_png = frames[max(frames)]
            candidate_img = load_image_rgb(candidate_png)

            if has_render_glitch(candidate_img) and attempt < max_retries:
                # Check if an earlier frame is clean
                clean_img = _find_clean_frame(frames)
                if clean_img is not None:
                    return DolphinRunOutcome(image=clean_img)
                logger.info("frame_retry_glitch", attempt=attempt + 1)
                continue

            return DolphinRunOutcome(image=candidate_img)
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

    return DolphinRunOutcome(
        image=None,
        crashed=True,
        returncode=last_result.returncode if last_result else -1,
        elapsed=last_result.elapsed_seconds if last_result else 0.0,
        run_seconds_budget=run_seconds,
    )


def _kill_orphan_dolphin(user_dir: Path) -> None:
    """Kill any Dolphin process still referencing this user_dir."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", str(user_dir)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in result.stdout.strip().splitlines():
            pid = line.strip()
            if pid:
                subprocess.run(["kill", "-9", pid], check=False, timeout=5)
    except Exception:
        pass  # best-effort cleanup


def _find_clean_frame(frames: dict[int, Path]) -> Any | None:
    """Walk backwards through frames to find one without a render glitch."""
    for key in sorted(frames.keys(), reverse=True):
        img = load_image_rgb(frames[key])
        if not has_render_glitch(img):
            return img
    return None
