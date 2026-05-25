"""Build an Inspect AI Sample + Task from web project/task files.

Unified builder: reads a JobSpec from the task config and wires
prompts, tools, and scorers accordingly. No more per-task-type branches.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from inspect_ai import Task as InspectTask
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessageUser, ContentImage, ContentText
from inspect_ai.solver import basic_agent, system_message

from src.agent.job_spec import Capability, EvaluationMethod, JobSpec
from src.agent.prompts.builder import build_system_prompt
from src.agent.scorer_builder import build_scorer
from src.agent.tools.builder import build_tools
from src.core.knowledge import FindingsStore
from src.core.sessions import Project, Task

# ── Unified Sample builder ────────────────────────────────────────────── #


def build_sample(task: Task, project: Project, spec: JobSpec) -> Sample:
    """Construct an Inspect AI Sample from a project task + JobSpec."""
    pcfg = project.config
    inv_block = f"\n{pcfg.inventory_text}\n" if pcfg.inventory_text else ""

    # Inject prior findings (exclude function kind — visible via Ghidra renames)
    findings_store = FindingsStore.load(project.root)
    findings_block = ""
    non_func = [f for f in findings_store.findings if f.kind != "function"]
    if non_func:
        findings_block = (
            f"\n## Prior findings from earlier tasks\n\n"
            f"{findings_store.format_table(exclude_kinds={'function'})}\n"
        )

    # Inject research index
    research_dir = project.root / "research"
    research_block = ""
    if research_dir.exists():
        index_path = research_dir / "INDEX.md"
        if index_path.exists():
            index_text = index_path.read_text().strip()
            docs = sorted(p.name for p in research_dir.glob("*.md") if p.name != "INDEX.md")
            if docs or "No research yet" not in index_text:
                research_block = f"\n## Research journal from earlier tasks\n\n{index_text}\n"
                if docs:
                    research_block += (
                        "\nAvailable docs: "
                        + ", ".join(docs)
                        + "\nUse `read_research(filename)` to read any of these.\n"
                    )

    # Inject savestate findings (if savestate assigned)
    ss_findings_block = ""
    if task.config.savestate_id:
        ss = project.get_savestate(task.config.savestate_id)
        if ss is not None:
            ss_store = FindingsStore.load(ss.root)
            if ss_store.findings:
                ss_findings_block = (
                    f"\n## Savestate findings (runtime-specific)\n\n"
                    f"{ss_store.format_table()}\n"
                )

    # Inject controller mapping (for runtime tasks)
    ctrl_block = ""
    if Capability.INPUT_INJECTION in spec.capabilities:
        from src.core.dolphin.controller_mapping import format_mapping_for_prompt, load_mapping

        ctrl_mapping = load_mapping(project.root)
        ctrl_block = f"\n## {format_mapping_for_prompt(ctrl_mapping)}\n"

    # Build the body
    body_parts = [f"Game: {pcfg.game_id}"]

    if spec.target_description:
        body_parts.append(f"Task: {spec.target_description}")

    if spec.uses_visual_gecko:
        body_parts.append(
            f"Scoring thresholds: HUD region mean diff >= {spec.hud_min_mean}, "
            f"preserve region mean diff <= {spec.preserve_max_mean}."
        )

    body_parts.append(inv_block)
    body_parts.append(findings_block)
    body_parts.append(research_block)
    body_parts.append(ss_findings_block)
    body_parts.append(ctrl_block)

    body = "\n".join(p for p in body_parts if p.strip())

    # Build content blocks
    content: list[ContentText | ContentImage] = [ContentText(text=body)]

    # Add reference frame + mask for visual tasks
    if spec.needs_mask and task.reference_path.exists() and task.mask_path.exists():
        content += [
            ContentText(text="Reference frame (current state):"),
            ContentImage(image=str(task.reference_path)),
            ContentText(text="Mask (white = target to remove, black = must preserve):"),
            ContentImage(image=str(task.mask_path)),
        ]

    return Sample(
        id=f"web_{project.project_id}_{task.task_id}",
        input=[ChatMessageUser(content=content)],
        target="",
        metadata={
            "project_id": project.project_id,
            "task_id": task.task_id,
            "game_id": pcfg.game_id,
        },
    )


# ── Unified Task builder ──────────────────────────────────────────────── #


def build_task_from_project_task(
    task: Task,
    project: Project,
    iso_path: Path,
    extract_root: Path,
) -> tuple[InspectTask, Callable[[], None]]:
    """Build a full Inspect AI Task from a web project task."""
    spec = task.config.get_job_spec()

    errors = spec.validate()
    if errors:
        raise ValueError(f"Invalid job spec: {'; '.join(errors)}")

    # Savestate enforcement
    if spec.needs_savestate and not task.config.savestate_id:
        raise ValueError("Job spec requires runtime capabilities but no savestate is assigned")

    # Reference frame + mask enforcement for pixel-diff tasks
    if spec.evaluation == EvaluationMethod.PIXEL_DIFF_MASK:
        if not task.reference_path.exists():
            raise ValueError(
                f"pixel_diff_mask task requires a reference frame but "
                f"{task.reference_path} does not exist. "
                f"Re-capture the reference frame in the task wizard."
            )
        if not task.mask_path.exists():
            raise ValueError(
                f"pixel_diff_mask task requires a HUD mask but "
                f"{task.mask_path} does not exist. "
                f"Paint the mask in the task wizard."
            )

    # Build prompt
    controller_mapping = ""
    if Capability.INPUT_INJECTION in spec.capabilities:
        from src.core.dolphin.controller_mapping import format_mapping_for_prompt, load_mapping

        controller_mapping = format_mapping_for_prompt(load_mapping(project.root))

    system_prompt = build_system_prompt(spec, controller_mapping=controller_mapping)

    # Build sample
    sample = build_sample(task, project, spec)

    # Session management
    session, session_ref, cleanup = _setup_session(spec, task, project, iso_path)

    # Resolve savestate root
    savestate_root = None
    savestate_path = None
    if task.config.savestate_id:
        ss = project.get_savestate(task.config.savestate_id)
        if ss is not None:
            savestate_root = ss.root
            savestate_path = ss.savestate_path

    # Build tools
    tools = build_tools(
        spec,
        project_root=project.root,
        iso_path=iso_path,
        extract_root=extract_root,
        session=session_ref or session,
        savestate_root=savestate_root,
        task_root=task.root,
        task_id=task.task_id,
        task=task,
        project=project,
        savestate_path=savestate_path,
    )

    # Build scorer — pass cleanup so the session stays alive for the eval
    scorer = build_scorer(
        spec,
        task=task,
        project=project,
        session_cleanup=cleanup,
    )

    # Build submit description based on goal type
    submit_desc = _submit_description(spec)

    task_name = task.config.name or f"task_{task.task_id}"
    inspect_task = InspectTask(
        dataset=[sample],
        solver=basic_agent(
            init=system_message(system_prompt),
            tools=tools,
            message_limit=spec.message_limit,
            **({"submit_description": submit_desc} if submit_desc else {}),
        ),
        scorer=scorer,
        name=task_name,
    )
    return inspect_task, cleanup


def _setup_session(
    spec: JobSpec,
    task: Task,
    project: Project,
    iso_path: Path,
) -> tuple[Any, Any, Any]:
    """Boot Dolphin session if needed. Returns (session, session_ref, cleanup_fn)."""
    if not spec.needs_dolphin_session:
        return None, None, lambda: None

    from src.core.dolphin.session import DolphinSession
    from src.core.dolphin.session_ref import SessionRef

    ss = project.get_savestate(task.config.savestate_id)
    if ss is None:
        raise ValueError(f"Savestate {task.config.savestate_id} not found")

    gdb_port = 6777 if Capability.RAM_POKE in spec.capabilities else None
    session_cm = DolphinSession.start(
        iso=iso_path,
        savestate=ss.savestate_path,
        pipe_input=Capability.INPUT_INJECTION in spec.capabilities,
        gdb_port=gdb_port,
    )
    raw_session = session_cm.__enter__()
    raw_session.wait_for_first_frame()

    # If interactive gecko is enabled, wrap in SessionRef for hot-swap
    if spec.uses_interactive_gecko:
        ref = SessionRef(raw_session)

        def _cleanup() -> None:
            try:
                current = ref.session
                # Clean up the gecko-swapped session's CM if it has one
                gecko_cm = getattr(current, "_gecko_cm", None)
                current.terminate()
                current.cleanup()
                if gecko_cm is not None:
                    gecko_cm.__exit__(None, None, None)
            except Exception:
                pass
            try:
                session_cm.__exit__(None, None, None)
            except Exception:
                pass

        return raw_session, ref, _cleanup
    else:

        def _cleanup() -> None:
            try:
                session_cm.__exit__(None, None, None)
            except Exception:
                pass

        return raw_session, None, _cleanup


def _submit_description(spec: JobSpec) -> str:
    """Build a submit description based on goal type."""
    from src.agent.job_spec import GoalType

    if spec.goal_type == GoalType.STATIC_RESEARCH:
        return (
            "Submit your research summary and end the task. "
            "Call this after you've saved findings and written "
            "research docs. Pass a concise summary of what you discovered."
        )
    elif spec.goal_type == GoalType.FIND_RAM_ADDRESS:
        return (
            "Submit your findings and end the task. "
            "Call this after you've saved the discovered addresses "
            "as savestate findings. Pass a summary of the addresses "
            "and how you verified them."
        )
    else:
        if spec.uses_interactive_gecko:
            return (
                "Submit your results and end the task. "
                "Call this after you've saved the working Gecko code via "
                "save_gecko_code(). Pass a summary of the code, what it "
                "patches, and how you verified it."
            )
        # Visual gecko: no special submit desc — agent submits gecko text as answer
        return ""
