"""Scoring math tests — no Dolphin involvement."""

from __future__ import annotations

import numpy as np
import pytest

from src.agent.scorer import score_against_mask


def _make_mask(h: int = 20, w: int = 20) -> np.ndarray:
    """Two halves: left = HUD (white), right = preserve (black)."""
    mask = np.zeros((h, w), dtype=np.uint8)
    mask[:, : w // 2] = 255
    return mask


def test_identical_frames_fail_hud_pass_preserve() -> None:
    """Candidate == reference: HUD diff is 0 (fail), preserve diff is 0 (pass)."""
    ref = np.full((20, 20, 3), 100, dtype=np.uint8)
    cand = ref.copy()
    mask = _make_mask()

    s = score_against_mask(ref, cand, mask, hud_min_mean=5.0, preserve_max_mean=2.0)
    assert s.hud_mean == 0.0
    assert s.preserve_mean == 0.0
    assert not s.hud_pass
    assert s.preserve_pass
    assert not s.passed


def test_hud_changed_preserve_intact_passes() -> None:
    """Big change in HUD half, zero change in preserve half: full PASS."""
    ref = np.full((20, 20, 3), 100, dtype=np.uint8)
    cand = ref.copy()
    cand[:, :10] = 200  # +100 in every channel in the HUD half
    mask = _make_mask()

    s = score_against_mask(ref, cand, mask, hud_min_mean=5.0, preserve_max_mean=2.0)
    assert s.hud_mean == 100.0
    assert s.preserve_mean == 0.0
    assert s.passed


def test_hud_changed_but_preserve_disturbed_fails() -> None:
    """HUD covered AND preserve region also moved: preservation fails."""
    ref = np.full((20, 20, 3), 100, dtype=np.uint8)
    cand = ref.copy()
    cand[:, :10] = 200
    cand[:, 10:] = 105  # +5 in preserve half — exceeds 2.0 threshold
    mask = _make_mask()

    s = score_against_mask(ref, cand, mask, hud_min_mean=5.0, preserve_max_mean=2.0)
    assert s.hud_pass
    assert not s.preserve_pass
    assert not s.passed


def test_shape_mismatch_raises() -> None:
    ref = np.zeros((20, 20, 3), dtype=np.uint8)
    cand = np.zeros((10, 10, 3), dtype=np.uint8)
    mask = _make_mask()
    with pytest.raises(ValueError, match="shape"):
        score_against_mask(ref, cand, mask)


def test_mask_without_white_raises() -> None:
    ref = np.zeros((20, 20, 3), dtype=np.uint8)
    cand = ref.copy()
    mask = np.zeros((20, 20), dtype=np.uint8)  # all-black
    with pytest.raises(ValueError, match="HUD"):
        score_against_mask(ref, cand, mask)
