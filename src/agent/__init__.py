"""Inspect AI agent loop for spectre.

Public surface:

- `hud_off` — the `@task` entry point (loaded by `inspect eval`)
- `score_against_mask` — pure scoring math; reused by both the tool's
  per-call feedback and the final scorer
"""

from src.agent.scorer import score_against_mask
from src.agent.task import hud_off

__all__ = ["hud_off", "score_against_mask"]
