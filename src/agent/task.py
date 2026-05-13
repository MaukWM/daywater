"""Inspect AI `@task` entry point for spectre.

One task class today: `hud_off`. Single sample (Nightfire) baked in so
`inspect eval src/agent/task.py` runs without further config.

Web-UI mode (later) will dynamically build a Sample from uploaded files
and call into the same `Task` factory with that dataset.
"""

from __future__ import annotations

from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.scorer import CORRECT, INCORRECT, Score, Scorer, Target, accuracy, scorer
from inspect_ai.solver import TaskState, basic_agent, system_message

from src.agent.loader import build_sample, load_sample_config, resolve_runtime_paths
from src.agent.prompts import SYSTEM_PROMPT
from src.agent.scorer import load_mask, score_against_mask
from src.agent.tools import run_gecko
from src.dolphin import (
    collect_dump,
    load_png_frames,
    parse_gecko,
    read_game_id,
    run_dolphin,
)
from src.dolphin.diff import load_image_rgb
from src.dolphin.runner import write_user_dir

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"
DEFAULT_SAMPLE = "nightfire_hud_off"


@scorer(metrics=[accuracy()])
def hud_off_scorer(sample_dir: Path) -> Scorer:
    """Grade the agent's last submission.

    Re-runs Dolphin with the agent's final answer text parsed as Gecko,
    scores the resulting frame against the mask. No reliance on tool-call
    state — final scoring stands alone and re-verifies.
    """
    cfg = load_sample_config(sample_dir)

    async def score(state: TaskState, target: Target) -> Score:
        gecko_text = state.output.completion or ""
        codes = parse_gecko(gecko_text)
        if not codes:
            return Score(
                value=INCORRECT,
                answer=gecko_text[:200],
                explanation="Final answer contained no parseable Gecko code.",
            )

        import shutil
        import tempfile

        iso, savestate = resolve_runtime_paths(cfg)
        tmp_root = Path(tempfile.mkdtemp(prefix="spectre_score_"))
        try:
            user_dir = tmp_root / "user"
            write_user_dir(user_dir, read_game_id(iso), codes)
            run_dolphin(
                user_dir=user_dir,
                iso=iso,
                log_path=tmp_root / "dolphin.log",
                savestate=savestate,
                run_seconds=cfg.run_seconds,
            )
            frames_dir = tmp_root / "frames"
            collect_dump(user_dir, frames_dir)
            frames = load_png_frames(frames_dir)
            if not frames:
                return Score(
                    value=INCORRECT,
                    answer=gecko_text[:200],
                    explanation="Final Dolphin run produced no frames.",
                )

            mask_score = score_against_mask(
                reference=load_image_rgb(sample_dir / "reference.png"),
                candidate=load_image_rgb(frames[max(frames)]),
                mask=load_mask(sample_dir / "mask.png"),
                hud_min_mean=cfg.score_hud_min_mean,
                preserve_max_mean=cfg.score_preserve_max_mean,
            )
            return Score(
                value=CORRECT if mask_score.passed else INCORRECT,
                answer=gecko_text[:200],
                explanation=(
                    f"hud_mean={mask_score.hud_mean:.2f} "
                    f"preserve_mean={mask_score.preserve_mean:.2f} "
                    f"{mask_score.verdict} — {mask_score.reason()}"
                ),
            )
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

    return score


@task
def hud_off() -> Task:
    """Single-Sample HUD-removal task (Nightfire reference instance)."""
    sample_dir = SAMPLES_DIR / DEFAULT_SAMPLE
    sample = build_sample(sample_dir)
    return Task(
        dataset=[sample],
        solver=basic_agent(
            init=system_message(SYSTEM_PROMPT),
            tools=[run_gecko(sample_dir)],
            message_limit=40,
        ),
        scorer=hud_off_scorer(sample_dir),
    )
