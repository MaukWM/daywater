"""Visual Gecko tool factory for pixel-diff HUD tasks.

Builds the ``run_gecko`` Inspect AI tool that runs Dolphin with candidate
Gecko codes and scores the result against a reference frame + mask.
"""

from __future__ import annotations

import base64
import io
from typing import TYPE_CHECKING

from inspect_ai.model import ContentImage, ContentText
from inspect_ai.tool import Tool, ToolResult, tool
from PIL import Image

from src.agent.job_spec import JobSpec
from src.agent.scorer import load_mask, score_against_mask
from src.agent.state import sample_store
from src.dolphin import parse_gecko
from src.dolphin.diff import load_image_rgb
from src.runner import run_dolphin_with_retry

if TYPE_CHECKING:
    from src.web.sessions import Project, Task


def build_run_gecko_for_task(task: "Task", project: "Project", spec: JobSpec) -> Tool:
    """Build the run_gecko tool for pixel-diff visual tasks."""

    # Pre-cache reference + mask at build time so we fail fast and only once.
    _reference_path = task.reference_path
    _mask_path = task.mask_path

    @tool
    def run_gecko() -> Tool:
        async def execute(gecko_text: str) -> ToolResult:
            """Run Dolphin with a candidate Gecko code and score the result.

            Args:
                gecko_text: One or more `$Name` blocks followed by 16-char hex
                    pair lines.
            """
            # Validate required assets exist before burning a budget slot.
            if not _reference_path.exists():
                return (
                    f"Error: reference frame not found at {_reference_path}. "
                    f"Go back to the task wizard and re-capture the reference frame."
                )
            if not _mask_path.exists():
                return (
                    f"Error: mask not found at {_mask_path}. "
                    f"Go back to the task wizard and paint the HUD mask."
                )

            call_idx = sample_store.increment_gecko_budget()

            codes = parse_gecko(gecko_text)
            if not codes:
                return f"Call {call_idx}: empty gecko text."

            iso_path = project.iso_path.resolve()
            ss = project.get_savestate(task.config.savestate_id)
            if ss is None:
                return "Error: no savestate assigned to this task."
            savestate_path = ss.savestate_path

            outcome = run_dolphin_with_retry(
                iso_path, savestate_path, codes, spec.run_seconds,
            )
            if outcome.image is None:
                return f"Call {call_idx}: {outcome.crash_detail}"

            mask_score = score_against_mask(
                reference=load_image_rgb(_reference_path),
                candidate=outcome.image,
                mask=load_mask(_mask_path),
                hud_min_mean=spec.hud_min_mean,
                preserve_max_mean=spec.preserve_max_mean,
            )

            if mask_score.passed:
                sample_store.set_last_pass_gecko(gecko_text)

            # Encode frame as data URL for multimodal feedback.
            img = Image.fromarray(outcome.image)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            data_url = f"data:image/png;base64,{b64}"

            verdict_text = (
                f"Call {call_idx} -- verdict: {mask_score.verdict}\n"
                f"  hud_mean      = {mask_score.hud_mean:.2f}  "
                f"(need >= {spec.hud_min_mean})\n"
                f"  preserve_mean = {mask_score.preserve_mean:.2f}  "
                f"(need <= {spec.preserve_max_mean})\n"
                f"  {mask_score.reason()}"
            )
            return [
                ContentText(text=verdict_text),
                ContentImage(image=data_url),
            ]

        return execute

    return run_gecko()
