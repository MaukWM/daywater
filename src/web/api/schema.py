"""Schema endpoint — capability, goal type, and evaluation method definitions."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/schema")
async def get_schema() -> dict:  # type: ignore[type-arg]
    """Return capability, goal type, and evaluation method definitions.

    The frontend reads this on boot so the UI never duplicates enum values.
    """
    from src.agent.job_spec import Capability, EvaluationMethod, GoalType

    return {
        "goal_types": [{"id": g.value, "name": g.value.replace("_", " ").title()} for g in GoalType],
        "evaluation_methods": [
            {"id": e.value, "name": e.value.replace("_", " ").title()} for e in EvaluationMethod
        ],
        "capabilities": [
            {
                "id": "static_re",
                "name": "Static RE",
                "desc": "Ghidra-based binary analysis: decompile functions, search strings, trace call graphs, rename/annotate.",
                "tag": "always on",
            },
            {
                "id": "discovery",
                "name": "ISO Discovery",
                "desc": "Walk the disc filesystem, extract binaries, run Ghidra analysis. Lets the agent find and switch between executables.",
                "tag": "always on",
            },
            {
                "id": "gecko_injection",
                "name": "Gecko Injection",
                "desc": "Write and test Gecko cheat codes. The agent can apply codes to Dolphin and verify them against the game.",
                "required_by": {"goal": ["find_code_patch"]},
            },
            {
                "id": "ram_poke",
                "name": "RAM Poke",
                "desc": "Read/scan/diff live GameCube memory, set write watchpoints to find which code writes to an address. Requires a savestate.",
                "required_by": {"goal": ["find_ram_address"]},
                "tag": "runtime — needs savestate",
            },
            {
                "id": "input_injection",
                "name": "Input Injection",
                "desc": "Send controller inputs to Dolphin: press buttons, hold sticks, sample position over time. Requires a savestate.",
                "tag": "runtime — needs savestate",
            },
            {
                "id": "frame_capture",
                "name": "Frame Capture",
                "desc": "Grab screenshots from the running Dolphin session for visual inspection.",
                "required_by": {"eval": ["pixel_diff_mask"]},
                "tag": "runtime — needs savestate",
            },
            {
                "id": "pixel_diff",
                "name": "Pixel Diff",
                "desc": "Compare captured frames against a reference using a painted mask.",
                "required_by": {"eval": ["pixel_diff_mask"]},
                "requires": ["frame_capture"],
                "hidden": True,
            },
        ],
    }
