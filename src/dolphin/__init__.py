"""Dolphin runner + scorer primitives.

Pure Python library. CLI wrappers live in `src.cli`. Inspect AI tools and
scorers (Phase C+) will sit alongside this module and call into it.

Public surface intentionally small:

- `read_game_id`               — peek the 6-byte GC disc header
- `parse_gecko` / `render_gecko_ini` — Gecko text ↔ Dolphin per-game INI
- `RunResult` / `run_dolphin`  — boot Dolphin headless, dump frames
- `collect_dump` / `extract_last_png` — frame post-processing
- `diff_stats` / `load_png_frames` — pixel-diff scorer primitives
"""

from src.dolphin.diff import diff_stats, load_png_frames
from src.dolphin.gecko import GeckoCode, parse_gecko, render_gecko_ini
from src.dolphin.runner import (
    RunResult,
    collect_dump,
    extract_last_png,
    read_game_id,
    run_dolphin,
)

__all__ = [
    "GeckoCode",
    "RunResult",
    "collect_dump",
    "diff_stats",
    "extract_last_png",
    "load_png_frames",
    "parse_gecko",
    "read_game_id",
    "render_gecko_ini",
    "run_dolphin",
]
