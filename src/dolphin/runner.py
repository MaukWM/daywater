"""Native macOS Dolphin runner — boot headless, dump frames.

This is the local dev path. The verifier container (Linux) lives under
`docker/` and is invoked by the Inspect AI sandbox in later phases.

The runner spawns Dolphin with an isolated `--user` dir so test runs never
pollute the developer's real Dolphin profile. On macOS the launcher uses
`open -gjn -W` to keep the cocoa window invisible while still emitting
software-rendered frames to the dump dir.

Pure-ish: filesystem side effects in a caller-supplied directory, plus
process spawn. No globals, no logging — caller handles UX.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.dolphin.gecko import GeckoCode, render_gecko_ini

DOLPHIN_BIN = Path("/Applications/Dolphin.app/Contents/MacOS/Dolphin")
DOLPHIN_APP = Path("/Applications/Dolphin.app")

VideoBackend = Literal["Software", "OGL", "Metal", "Vulkan", "Null"]

DEFAULT_DOLPHIN_INI = """[General]
ShowLag = False
ShowFrameCount = False

[Core]
CPUCore = 1
Fastmem = True
CPUThread = True
DSPHLE = True
EnableCheats = True
SyncOnSkipIdle = True

[DSP]
Backend = Null

[Display]
Fullscreen = False
RenderToMain = False

[Movie]
DumpFrames = True
DumpFramesSilent = True
"""

DEFAULT_GFX_INI = """[Hardware]
VSync = False

[Settings]
ShowFPS = False
LogRenderTimeToFile = False
AspectRatio = 0
Crop = False
"""


@dataclass(frozen=True)
class RunResult:
    """Outcome of a Dolphin run."""

    returncode: int
    elapsed_seconds: float
    user_dir: Path
    log_path: Path


def read_game_id(iso_path: Path) -> str:
    """First six bytes of a GameCube disc image are the game ID (ASCII)."""
    with iso_path.open("rb") as f:
        return f.read(6).decode("ascii", errors="replace")


def write_user_dir(user_dir: Path, game_id: str, gecko_codes: list[GeckoCode]) -> None:
    """Lay down a minimal isolated Dolphin user dir + optional Gecko INI."""
    (user_dir / "Config").mkdir(parents=True, exist_ok=True)
    (user_dir / "GameSettings").mkdir(parents=True, exist_ok=True)
    (user_dir / "Dump" / "Frames").mkdir(parents=True, exist_ok=True)

    (user_dir / "Config" / "Dolphin.ini").write_text(DEFAULT_DOLPHIN_INI)
    (user_dir / "Config" / "GFX.ini").write_text(DEFAULT_GFX_INI)

    ini_text = render_gecko_ini(gecko_codes)
    if ini_text:
        (user_dir / "GameSettings" / f"{game_id}.ini").write_text(ini_text)


def run_dolphin(
    user_dir: Path,
    iso: Path,
    log_path: Path,
    *,
    savestate: Path | None = None,
    video_backend: VideoBackend = "Software",
    run_seconds: int = 20,
    hidden: bool = True,
) -> RunResult:
    """Boot Dolphin with the supplied user dir; SIGTERM after `run_seconds`.

    Caller is responsible for pre-populating `user_dir` (Gecko INI, etc.) via
    `write_user_dir`. `log_path` receives Dolphin's combined stdout/stderr.
    """
    dolphin_args = [
        "--batch",
        f"--user={user_dir}",
        f"--video_backend={video_backend}",
        "--audio_emulation=HLE",
        f"--exec={iso}",
    ]
    if savestate is not None:
        dolphin_args.append(f"--save_state={savestate}")

    env = os.environ.copy()
    env.setdefault("LC_ALL", "en_US.UTF-8")

    if hidden:
        # `open -gjn -W` launches a fresh hidden Dolphin instance and blocks until
        # it exits. Window exists but never visible; software renderer still
        # writes frames to the dump dir.
        args = ["open", "-gjn", "-W", "-a", str(DOLPHIN_APP), "--args", *dolphin_args]
    else:
        args = [str(DOLPHIN_BIN), *dolphin_args]

    t0 = time.time()
    with log_path.open("wb") as logf:
        proc = subprocess.Popen(args, stdout=logf, stderr=subprocess.STDOUT, env=env)
        try:
            proc.wait(timeout=run_seconds)
        except subprocess.TimeoutExpired:
            _terminate(proc, hidden=hidden)
    elapsed = time.time() - t0

    return RunResult(
        returncode=proc.returncode if proc.returncode is not None else -1,
        elapsed_seconds=elapsed,
        user_dir=user_dir,
        log_path=log_path,
    )


def _terminate(proc: subprocess.Popen[bytes], *, hidden: bool) -> None:
    """Stop Dolphin cleanly; escalate to SIGKILL if it ignores SIGTERM.

    `open -W` does not propagate signals to the launched cocoa app, so when
    launched hidden we kill by binary name instead of via the wrapper PID.
    """
    if hidden:
        subprocess.run(
            ["pkill", "-TERM", "-f", "Dolphin.app/Contents/MacOS/Dolphin"],
            check=False,
        )
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            subprocess.run(
                ["pkill", "-KILL", "-f", "Dolphin.app/Contents/MacOS/Dolphin"],
                check=False,
            )
            proc.wait(timeout=5)
    else:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def collect_dump(user_dir: Path, out_dir: Path) -> list[Path]:
    """Copy every file in `<user_dir>/Dump/Frames/` to `out_dir`."""
    src = user_dir / "Dump" / "Frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    collected: list[Path] = []
    if not src.exists():
        return collected
    for entry in src.iterdir():
        if entry.is_file():
            dst = out_dir / entry.name
            shutil.copy2(entry, dst)
            collected.append(dst)
    return collected


def extract_last_png(avi_path: Path, png_path: Path) -> bool:
    """Pull the last frame of an AVI dump as PNG via ffmpeg.

    Returns True iff the PNG was written and is non-empty. Newer Dolphin
    builds dump PNG sequences and skip this entirely; older builds (debian
    5.0-17995, master with `DumpFramesAsImages = False`) dump FFV1 AVI.
    """
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-sseof", "-1", "-i", str(avi_path),
                "-vsync", "0", "-update", "1", "-q:v", "2", str(png_path),
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"ffmpeg failed: {exc.stderr.decode(errors='replace')}\n")
        return False
    return png_path.exists() and png_path.stat().st_size > 0
