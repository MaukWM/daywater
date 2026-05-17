"""Inspect AI `@task` entry point for Spectre.

Unified entry point: accepts a preset name or a JSON job spec file.
Backwards-compatible: `inspect eval src/agent/task.py` still runs HUD removal.
"""

from __future__ import annotations

from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.solver import basic_agent, system_message

from src.agent.discovery import format_inventory, survey_and_analyze
from src.agent.job_spec import Capability, JobSpec
from src.agent.loader import (
    build_sample,
    load_sample_config,
    resolve_optional_user_binary,
    resolve_runtime_paths,
)
from src.agent.presets import get_preset
from src.agent.prompts.builder import build_system_prompt
from src.agent.tool_builder import build_tools
from src.dolphin import read_game_id

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"
SPECTRE_ROOT = Path(__file__).resolve().parents[2]
EXTRACT_ROOT = SPECTRE_ROOT / "cache" / "extracted"
DEFAULT_SAMPLE = "nightfire_hud_off"


def _extract_root_for(iso_path: Path) -> Path:
    """Scratch directory under `cache/extracted/` for files pulled from the ISO."""
    return EXTRACT_ROOT / iso_path.stem


@task
def spectre_task(
    preset: str = "hud_removal",
    job_spec_path: str = "",
    iso: str = "",
    savestate: str = "",
) -> Task:
    """Unified Spectre task entry point.

    Args:
        preset: Name of a preset (hud_removal, position_finding, noclip, research).
        job_spec_path: Path to a JSON job spec file (overrides preset).
        iso: Path to the game ISO. Overrides env var.
        savestate: Path to the Dolphin savestate. Overrides env var.

    CLI usage::

        inspect eval src/agent/task.py -T preset=hud_removal -T iso=roms/nightfire.iso -T savestate=roms/GO7E69.s01
        inspect eval src/agent/task.py -T preset=research -T iso=roms/nightfire.iso
    """
    import os

    # Load job spec
    if job_spec_path:
        spec = JobSpec.from_json(Path(job_spec_path).read_text())
    else:
        spec = get_preset(preset)

    # For CLI mode, we use the legacy sample config to resolve ISO/savestate paths.
    # This maintains backwards compat with the env-var-based CLI workflow.
    sample_dir = SAMPLES_DIR / DEFAULT_SAMPLE
    cfg = load_sample_config(sample_dir)

    if iso:
        os.environ[cfg.iso_env] = iso
    if savestate:
        os.environ[cfg.savestate_env] = savestate

    iso_path, _ = resolve_runtime_paths(cfg)
    extract_root = _extract_root_for(iso_path)
    extract_root.mkdir(parents=True, exist_ok=True)

    # CLI mode: persist findings under sessions/_cli/<game_id>/
    game_id = read_game_id(iso_path)
    cli_project_root = SPECTRE_ROOT / "sessions" / "_cli" / game_id
    cli_project_root.mkdir(parents=True, exist_ok=True)

    # Include the user's env-supplied ELF (if any).
    extras: list[Path] = []
    user_binary = resolve_optional_user_binary(cfg)
    if user_binary is not None:
        extras.append(user_binary)

    # Pre-analyze every executable on the disc.
    inventory = survey_and_analyze(iso_path, extract_root, extras=extras)
    inventory_text = format_inventory(inventory)

    # Build sample using the old loader (CLI mode doesn't have web Task/Project)
    sample = build_sample(sample_dir, inventory_text=inventory_text, project_root=cli_project_root)

    # Build prompt
    system_prompt = build_system_prompt(spec)

    # Build tools (CLI mode: no Dolphin session, no savestate)
    tools = build_tools(
        spec,
        project_root=cli_project_root,
        iso_path=iso_path,
        extract_root=extract_root,
    )

    # For HUD tasks in CLI mode, add the legacy run_gecko tool
    if spec.uses_visual_gecko:
        from src.agent.tools import run_gecko

        tools.insert(0, run_gecko(sample_dir))

    # Simple scorer for CLI mode
    from src.agent.scorer_builder import build_scorer

    scorer = build_scorer(spec)

    return Task(
        dataset=[sample],
        solver=basic_agent(
            init=system_message(system_prompt),
            tools=tools,
            message_limit=spec.message_limit,
        ),
        scorer=scorer,
    )


# Backwards compat: `inspect eval src/agent/task.py` still works
hud_off = spectre_task
