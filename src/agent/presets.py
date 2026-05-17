"""Preset job specs for the 4 standard Spectre task types.

Each preset is a pre-filled JobSpec. Users can select a preset and tweak
any field before running.
"""

from __future__ import annotations

from src.agent.job_spec import (
    Capability,
    EvaluationMethod,
    GoalType,
    InputMutationHint,
    JobSpec,
)

PRESETS: dict[str, JobSpec] = {
    "hud_removal": JobSpec(
        goal_type=GoalType.FIND_CODE_PATCH,
        capabilities={
            Capability.STATIC_RE,
            Capability.DISCOVERY,
            Capability.GECKO_INJECTION,
            Capability.FRAME_CAPTURE,
            Capability.PIXEL_DIFF,
        },
        evaluation=EvaluationMethod.PIXEL_DIFF_MASK,
        target_description="Remove all HUD/overlay elements marked in the mask.",
        max_gecko_runs=8,
    ),
    "position_finding": JobSpec(
        goal_type=GoalType.FIND_RAM_ADDRESS,
        capabilities={
            Capability.STATIC_RE,
            Capability.DISCOVERY,
            Capability.RAM_POKE,
            Capability.INPUT_INJECTION,
        },
        evaluation=EvaluationMethod.MANUAL_REVIEW,
        target_description="Find RAM addresses for player X/Y/Z coordinates.",
        input_mutation_hints=[
            InputMutationHint("stick_main forward", "X or Z value increases"),
            InputMutationHint("stick_main backward", "X or Z value decreases"),
        ],
    ),
    "noclip": JobSpec(
        goal_type=GoalType.FIND_CODE_PATCH,
        capabilities={
            Capability.STATIC_RE,
            Capability.DISCOVERY,
            Capability.GECKO_INJECTION,
            Capability.RAM_POKE,
            Capability.INPUT_INJECTION,
            Capability.FRAME_CAPTURE,
        },
        evaluation=EvaluationMethod.MANUAL_REVIEW,
        target_description="Find a Gecko code that enables free flight movement (noclip).",
    ),
    "research": JobSpec(
        goal_type=GoalType.STATIC_RESEARCH,
        capabilities={
            Capability.STATIC_RE,
            Capability.DISCOVERY,
        },
        evaluation=EvaluationMethod.MANUAL_REVIEW,
        target_description="Analyze binary structure and document findings.",
    ),
}

PRESET_DESCRIPTIONS: dict[str, str] = {
    "hud_removal": "Find a Gecko code that removes HUD elements (scored via pixel diff against a mask)",
    "position_finding": "Find RAM addresses for player position (X/Y/Z coordinates)",
    "noclip": "Find a Gecko code that enables free 3D flight through walls",
    "research": "Open-ended static analysis — explore and document the codebase",
}


def get_preset(name: str) -> JobSpec:
    """Return a deep copy of a preset spec."""
    if name not in PRESETS:
        raise ValueError(f"Unknown preset: {name}. Available: {', '.join(PRESETS)}")
    return JobSpec.from_dict(PRESETS[name].to_dict())
