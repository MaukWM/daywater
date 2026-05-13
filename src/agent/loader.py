"""Sample loader: build an Inspect AI `Sample` from a sample directory.

A sample dir holds the static side of one task instance:

- `sample.toml`   — typed config (id, env vars, run/budget/thresholds)
- `hint.txt`      — natural-language brief shown to the agent
- `reference.png` — baseline frame (no cheat) shown to the agent
- `mask.png`      — B&W HUD mask shown to the agent and used by the scorer
- `expected.gecko`— ground-truth solution (sanity only; not shown)

The licensed ROM + savestate are resolved from env vars at load time so
nothing copyrighted enters the repo.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageUser, ContentImage, ContentText

from src.agent.prompts import TASK_INPUT_PREFIX


@dataclass(frozen=True)
class SampleConfig:
    """Typed view of `sample.toml`."""

    id: str
    game_id: str
    description: str
    iso_env: str
    savestate_env: str
    binary_env: str | None       # optional ELF/DOL override env var name
    run_seconds: int
    verify_budget: int
    score_hud_min_mean: float
    score_preserve_max_mean: float


def load_sample_config(sample_dir: Path) -> SampleConfig:
    raw = tomllib.loads((sample_dir / "sample.toml").read_text())
    return SampleConfig(
        id=raw["id"],
        game_id=raw["game_id"],
        description=raw.get("description", ""),
        iso_env=raw["iso_env"],
        savestate_env=raw["savestate_env"],
        binary_env=raw.get("binary_env"),
        run_seconds=int(raw["run_seconds"]),
        verify_budget=int(raw["verify_budget"]),
        score_hud_min_mean=float(raw["score_hud_min_mean"]),
        score_preserve_max_mean=float(raw["score_preserve_max_mean"]),
    )


def resolve_runtime_paths(cfg: SampleConfig) -> tuple[Path, Path]:
    """Resolve ISO + savestate paths from env vars. Raises if missing."""
    iso = os.environ.get(cfg.iso_env)
    sav = os.environ.get(cfg.savestate_env)
    if not iso or not sav:
        missing = [name for name, val in [(cfg.iso_env, iso), (cfg.savestate_env, sav)] if not val]
        raise RuntimeError(f"env vars not set: {missing}")
    iso_path = Path(iso).expanduser().resolve()
    sav_path = Path(sav).expanduser().resolve()
    if not iso_path.exists():
        raise FileNotFoundError(f"ISO not found at {iso_path} (from {cfg.iso_env})")
    if not sav_path.exists():
        raise FileNotFoundError(f"savestate not found at {sav_path} (from {cfg.savestate_env})")
    return iso_path, sav_path


def resolve_binary_for_analysis(cfg: SampleConfig, sample_dir: Path) -> Path:
    """Return the binary Ghidra should analyze.

    Preference order:
    1. `binary_env` from sample.toml, if set and the path exists. Typically
       points at a full ELF reconstructed by a decomp project — covers RELs
       and the entire address space.
    2. `<sample_dir>/boot.dol` (extracted from the ISO by `extract_dol`).
       Lower fidelity: REL-loaded code is invisible.
    """
    if cfg.binary_env:
        raw = os.environ.get(cfg.binary_env)
        if raw:
            p = Path(raw).expanduser().resolve()
            if p.exists():
                return p
    dol = (sample_dir / "boot.dol").resolve()
    if dol.exists():
        return dol
    raise FileNotFoundError(
        f"no analyzable binary: set {cfg.binary_env} to a real ELF, "
        f"or run `scripts/build_analysis.py` to extract {dol} from the ISO first"
    )


def build_sample(sample_dir: Path) -> Sample:
    """Construct one Inspect AI `Sample` from a sample directory."""
    cfg = load_sample_config(sample_dir)
    hint = (sample_dir / "hint.txt").read_text().strip()
    reference_png = sample_dir / "reference.png"
    mask_png = sample_dir / "mask.png"

    if not reference_png.exists() or not mask_png.exists():
        raise FileNotFoundError(
            f"reference.png or mask.png missing in {sample_dir}; "
            f"run scripts/gen_<sample>_assets.py first"
        )

    body = (
        f"{TASK_INPUT_PREFIX}\n\n"
        f"Game: {cfg.description} (ID `{cfg.game_id}`).\n"
        f"Budget: {cfg.verify_budget} tool calls.\n"
        f"Scoring thresholds: HUD region mean diff ≥ {cfg.score_hud_min_mean}, "
        f"preserve region mean diff ≤ {cfg.score_preserve_max_mean}.\n\n"
        f"Hint:\n{hint}"
    )

    user_message = ChatMessageUser(
        content=[
            ContentText(text=body),
            ContentText(text="Reference frame (HUD currently present):"),
            ContentImage(image=str(reference_png)),
            ContentText(text="Mask (white = HUD to remove, black = must preserve):"),
            ContentImage(image=str(mask_png)),
        ],
    )

    return Sample(
        id=cfg.id,
        input=[user_message],
        target="",  # task is open-ended; scorer reads from sandbox state, not target
        metadata={
            "sample_dir": str(sample_dir),
            "config": cfg.__dict__,
        },
    )
