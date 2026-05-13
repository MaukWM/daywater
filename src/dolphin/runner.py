"""Cross-platform Dolphin runner — boot headless, dump frames.

Supports macOS (cocoa app via `open -gjn -W`) and Linux (`dolphin-emu-nogui
--platform=headless`). The runner spawns Dolphin with an isolated `--user`
dir so test runs never pollute the developer's real Dolphin profile.

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

# --- Platform detection -------------------------------------------------- #

_IS_MACOS = sys.platform == "darwin"
_IS_LINUX = sys.platform == "linux"

# macOS paths
DOLPHIN_APP = Path("/Applications/Dolphin.app")
DOLPHIN_MAC_BIN = DOLPHIN_APP / "Contents" / "MacOS" / "Dolphin"

# Linux: prefer dolphin-emu-nogui (true headless), fall back to dolphin-emu
DOLPHIN_LINUX_NOGUI = "dolphin-emu-nogui"
DOLPHIN_LINUX_GUI = "dolphin-emu"

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
EnableJIT = False
Volume = 0

[Display]
Fullscreen = False
RenderToMain = False

[Movie]
DumpFrames = True
DumpFramesSilent = True
DumpFramesAsImages = True
"""

DEFAULT_GFX_INI = """[Hardware]
VSync = False

[Settings]
ShowFPS = False
LogRenderTimeToFile = False
AspectRatio = 0
Crop = False
DumpFramesAsImages = True
"""


def _find_linux_dolphin() -> str:
    """Return the name of the best available Dolphin binary on Linux.

    Checks $PATH first, then /usr/games (Debian/Ubuntu installs there).
    """
    for name in (DOLPHIN_LINUX_NOGUI, DOLPHIN_LINUX_GUI):
        found = shutil.which(name)
        if found:
            return found
    # Debian/Ubuntu put game binaries in /usr/games, often not in PATH
    for name in (DOLPHIN_LINUX_NOGUI, DOLPHIN_LINUX_GUI):
        path = Path(f"/usr/games/{name}")
        if path.exists():
            return str(path)
    raise FileNotFoundError(
        f"Neither {DOLPHIN_LINUX_NOGUI} nor {DOLPHIN_LINUX_GUI} found in PATH or /usr/games. "
        "Install Dolphin (e.g. `nix develop` in the spectre directory)."
    )


def read_savestate_dolphin_version(savestate_path: Path) -> str | None:
    """Read the Dolphin version string from a savestate header.

    Returns the version string (e.g. "Dolphin [master] 2603a") or None if
    the header can't be parsed.
    """
    try:
        with savestate_path.open("rb") as f:
            f.seek(0x20)
            raw = f.read(64)
            # Version string is null-terminated ASCII starting at offset 0x20
            end = raw.find(b"\x00")
            if end > 0:
                return raw[:end].decode("ascii", errors="replace")
    except OSError:
        pass
    return None


def _get_running_dolphin_version() -> str | None:
    """Query the installed Dolphin binary for its version string."""
    try:
        if _IS_LINUX:
            dolphin_bin = _find_linux_dolphin()
        elif _IS_MACOS:
            dolphin_bin = str(DOLPHIN_MAC_BIN)
        else:
            return None
        result = subprocess.run(
            [dolphin_bin, "--version"],
            capture_output=True, text=True, timeout=5,
        )
        # Output is like "Dolphin [master] 2603a" or "Dolphin 5.0-17995-g..."
        version = (result.stdout.strip() or result.stderr.strip()).split("\n")[0]
        return version if version else None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _extract_build_number(version_str: str) -> str | None:
    """Extract the numeric build identifier from a Dolphin version string.

    "Dolphin [master] 2603a" -> "2603"
    "Dolphin 5.0-17995-g..."  -> "17995"
    """
    import re

    # Modern master: "Dolphin [master] 2603a" or "Dolphin [master] 2603"
    m = re.search(r"\]\s*(\d+)", version_str)
    if m:
        return m.group(1)
    # Debian stable: "Dolphin 5.0-17995-g..."
    m = re.search(r"5\.0-(\d+)", version_str)
    if m:
        return m.group(1)
    return None


def check_savestate_compatibility(savestate_path: Path) -> None:
    """Raise RuntimeError if the savestate was made with an incompatible Dolphin build.

    Compares the build number embedded in the savestate header against the
    running Dolphin binary. Mismatches cause silent load failures (Dolphin
    falls through to the title screen).
    """
    sav_ver = read_savestate_dolphin_version(savestate_path)
    if not sav_ver:
        return  # can't parse header, skip check

    run_ver = _get_running_dolphin_version()
    if not run_ver:
        return  # can't determine running version, skip check

    sav_build = _extract_build_number(sav_ver)
    run_build = _extract_build_number(run_ver)

    if sav_build and run_build and sav_build != run_build:
        raise RuntimeError(
            f"Savestate was created with {sav_ver!r} but the installed "
            f"Dolphin is {run_ver!r} (build {run_build} != {sav_build}). "
            f"Savestates are not portable across Dolphin versions — the game "
            f"will silently load to the title screen. Create a new savestate "
            f"with the current Dolphin build."
        )


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


def _build_command(
    user_dir: Path,
    iso: Path,
    *,
    savestate: Path | None,
    video_backend: VideoBackend,
    hidden: bool,
) -> tuple[list[str], bool]:
    """Build the Dolphin command line for the current platform.

    Returns (args, uses_open_wrapper) — the bool indicates whether macOS
    `open -W` was used, which affects signal propagation in _terminate.
    """
    if _IS_MACOS:
        # macOS GUI binary uses long flags
        dolphin_args = [
            "--batch",
            f"--user={user_dir}",
            f"--video_backend={video_backend}",
            "--audio_emulation=HLE",
            f"--exec={iso}",
        ]
        if savestate is not None:
            dolphin_args.append(f"--save_state={savestate}")

        if hidden:
            # `open -gjn -W` launches a fresh hidden cocoa instance and blocks
            # until it exits. Window exists but never visible; software renderer
            # still writes frames to the dump dir.
            return (
                ["open", "-gjn", "-W", "-a", str(DOLPHIN_APP), "--args", *dolphin_args],
                True,
            )
        return ([str(DOLPHIN_MAC_BIN), *dolphin_args], False)

    if _IS_LINUX:
        dolphin_bin = _find_linux_dolphin()
        # dolphin-emu-nogui uses short flags and has no --batch
        dolphin_args = [
            f"-u{user_dir}",
            f"-v{video_backend}",
            f"-e{iso}",
            "-CMovie.DumpFramesAsImages=True",
        ]
        if savestate is not None:
            dolphin_args.append(f"-s{savestate}")

        # Headless display strategy:
        # 1. If no DISPLAY and xvfb-run is available (Docker / CI): use xvfb
        #    to provide a virtual X11 display. Do NOT use -pheadless because
        #    older Dolphin builds (Debian 5.0-17995) fail to init the Software
        #    backend in headless mode.
        # 2. If DISPLAY is set or xvfb is absent: use -pheadless (works on
        #    modern builds like nix 2603a) or assume a display exists.
        if not os.environ.get("DISPLAY") and shutil.which("xvfb-run"):
            return (
                ["xvfb-run", "-a", "-s", "-screen 0 640x480x24", dolphin_bin, *dolphin_args],
                False,
            )
        if dolphin_bin.endswith(DOLPHIN_LINUX_NOGUI):
            dolphin_args.insert(0, "-pheadless")
        return ([dolphin_bin, *dolphin_args], False)

    raise RuntimeError(f"Unsupported platform: {sys.platform}")


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

    Raises RuntimeError if the savestate was created with an incompatible
    Dolphin build (prevents silent title-screen fallthrough).
    """
    if savestate is not None:
        check_savestate_compatibility(savestate)

    args, uses_open_wrapper = _build_command(
        user_dir,
        iso,
        savestate=savestate,
        video_backend=video_backend,
        hidden=hidden,
    )

    env = os.environ.copy()
    env.setdefault("LC_ALL", "en_US.UTF-8")

    t0 = time.time()
    with log_path.open("wb") as logf:
        proc = subprocess.Popen(args, stdout=logf, stderr=subprocess.STDOUT, env=env)
        try:
            proc.wait(timeout=run_seconds)
        except subprocess.TimeoutExpired:
            _terminate(proc, uses_open_wrapper=uses_open_wrapper)
    elapsed = time.time() - t0

    return RunResult(
        returncode=proc.returncode if proc.returncode is not None else -1,
        elapsed_seconds=elapsed,
        user_dir=user_dir,
        log_path=log_path,
    )


def _terminate(proc: subprocess.Popen[bytes], *, uses_open_wrapper: bool) -> None:
    """Stop Dolphin cleanly; escalate to SIGKILL if it ignores SIGTERM.

    macOS `open -W` does not propagate signals to the launched cocoa app,
    so when launched via the wrapper we kill by binary name instead.
    On Linux we signal the process directly.
    """
    if uses_open_wrapper:
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
