"""Smoke test: run the sample's `expected.gecko` through the scorer.

Reproduces what the `@scorer` in `src.agent.task` would do at the end of
an Inspect AI run, but skips the agent — feeds the ground-truth Gecko
straight in. If this prints PASS, the verifier pipeline is intact and
any failures during an actual eval are agent-side, not infra-side.

    uv run python scripts/smoke_test_expected.py [sample_name]

Defaults to `nightfire_hud_off`.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from src.agent.loader import load_sample_config, resolve_runtime_paths
from src.agent.scorer import load_mask, score_against_mask
from src.dolphin import collect_dump, load_png_frames, parse_gecko, read_game_id, run_dolphin
from src.dolphin.diff import load_image_rgb
from src.dolphin.runner import write_user_dir
from src.logging import logger

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples"


def main() -> int:
    sample_name = sys.argv[1] if len(sys.argv) > 1 else "nightfire_hud_off"
    sample_dir = SAMPLES_DIR / sample_name
    if not sample_dir.is_dir():
        logger.error("sample_not_found", path=str(sample_dir))
        return 2

    cfg = load_sample_config(sample_dir)
    expected_path = sample_dir / "expected.gecko"
    if not expected_path.exists():
        logger.error("expected_gecko_missing", path=str(expected_path))
        return 2

    codes = parse_gecko(expected_path.read_text())
    if not codes:
        logger.error("expected_gecko_empty", path=str(expected_path))
        return 2

    iso, savestate = resolve_runtime_paths(cfg)
    logger.info("smoke_start", sample=cfg.id, codes=[c.name for c in codes])

    tmp_root = Path(tempfile.mkdtemp(prefix="spectre_smoke_"))
    try:
        user_dir = tmp_root / "user"
        write_user_dir(user_dir, read_game_id(iso), codes)
        result = run_dolphin(
            user_dir=user_dir,
            iso=iso,
            log_path=tmp_root / "dolphin.log",
            savestate=savestate,
            run_seconds=cfg.run_seconds,
        )
        logger.info("dolphin_done", rc=result.returncode, elapsed=round(result.elapsed_seconds, 1))

        frames_dir = tmp_root / "frames"
        collect_dump(user_dir, frames_dir)
        frames = load_png_frames(frames_dir)
        if not frames:
            logger.error("no_frames")
            return 1

        last_idx = max(frames)
        score = score_against_mask(
            reference=load_image_rgb(sample_dir / "reference.png"),
            candidate=load_image_rgb(frames[last_idx]),
            mask=load_mask(sample_dir / "mask.png"),
            hud_min_mean=cfg.score_hud_min_mean,
            preserve_max_mean=cfg.score_preserve_max_mean,
        )
        logger.info(
            "smoke_result",
            verdict=score.verdict,
            hud_mean=round(score.hud_mean, 2),
            preserve_mean=round(score.preserve_mean, 2),
            hud_threshold=cfg.score_hud_min_mean,
            preserve_threshold=cfg.score_preserve_max_mean,
            reason=score.reason(),
        )
        return 0 if score.passed else 1
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
