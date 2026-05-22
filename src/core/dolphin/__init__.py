"""Dolphin runner + scorer primitives.

Pure Python library. CLI wrappers live in `src.cli`. Inspect AI tools and
scorers (Phase C+) will sit alongside this module and call into it.

Public surface:

- `read_game_id`               — peek the 6-byte GC disc header
- `parse_gecko` / `render_gecko_ini` — Gecko text ↔ Dolphin per-game INI
- `RunResult` / `run_dolphin`  — boot Dolphin headless, dump frames
- `collect_dump` / `extract_last_png` — frame post-processing
- `diff_stats` / `load_png_frames` — pixel-diff scorer primitives
- `InputSequence` / `play_inputs` — pipe-based controller input injection
- `read_gc_float` / `read_gc_u32` etc. — process memory reads (Linux)
- `MemoryWatcherListener`      — continuous address monitoring via Dolphin built-in
- `DolphinSession`             — interactive session (input + memory + lifecycle)
"""

from src.core.dolphin.debugger import GDBClient, WriteHit, find_writers
from src.core.dolphin.diff import diff_stats, load_png_frames
from src.core.dolphin.gecko import GeckoCode, parse_gecko, render_gecko_ini
from src.core.dolphin.input import InputSequence, play_inputs, setup_pipe_input
from src.core.dolphin.memory import (
    DolphinMemoryError,
    read_gc_bytes,
    read_gc_float,
    read_gc_floats,
    read_gc_u32,
)
from src.core.dolphin.runner import (
    RunResult,
    check_savestate_compatibility,
    collect_dump,
    extract_last_png,
    read_game_id,
    read_savestate_dolphin_version,
    run_dolphin,
)
from src.core.dolphin.session import DolphinSession
from src.core.dolphin.watcher import MemoryWatcherListener, PositionSample

__all__ = [
    "DolphinMemoryError",
    "DolphinSession",
    "GDBClient",
    "GeckoCode",
    "InputSequence",
    "MemoryWatcherListener",
    "PositionSample",
    "RunResult",
    "check_savestate_compatibility",
    "collect_dump",
    "diff_stats",
    "extract_last_png",
    "load_png_frames",
    "parse_gecko",
    "play_inputs",
    "read_game_id",
    "read_gc_bytes",
    "read_gc_float",
    "read_gc_floats",
    "read_gc_u32",
    "read_savestate_dolphin_version",
    "render_gecko_ini",
    "WriteHit",
    "find_writers",
    "run_dolphin",
    "setup_pipe_input",
]
