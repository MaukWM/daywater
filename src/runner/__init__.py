"""Eval-lifecycle runner: Dolphin retry, frame capture, orphan kill.

Sits between the dolphin subprocess wrapper (src.dolphin) and the
agent/web orchestration layers. No imports from src.agent or src.web.
"""

from src.runner.dolphin_runner import (
    DolphinRunOutcome,
    run_dolphin_with_retry,
)

__all__ = ["DolphinRunOutcome", "run_dolphin_with_retry"]
