"""Unified job specification for Spectre RE tasks.

Every RE task — preset or custom — is expressed as a configuration across
7 axes. The system wires prompts, tools, and scorers from this spec.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class GoalType(StrEnum):
    FIND_RAM_ADDRESS = "find_ram_address"
    FIND_CODE_PATCH = "find_code_patch"
    STATIC_RESEARCH = "static_research"


class Capability(StrEnum):
    STATIC_RE = "static_re"
    DISCOVERY = "discovery"
    GECKO_INJECTION = "gecko_injection"
    RAM_POKE = "ram_poke"
    INPUT_INJECTION = "input_injection"
    FRAME_CAPTURE = "frame_capture"
    PIXEL_DIFF = "pixel_diff"


class EvaluationMethod(StrEnum):
    PIXEL_DIFF_MASK = "pixel_diff_mask"
    MANUAL_REVIEW = "manual_review"


@dataclass
class InputMutationHint:
    """Structured hint: 'this input causes this expected change'."""

    input_description: str
    expected_effect: str


@dataclass
class JobSpec:
    """Complete specification for an RE task.

    Axes:
        1. goal_type — what the agent produces
        2. capabilities — which tools the agent gets (multi-select)
        3. evaluation — how the system judges the run
        4. target_description — natural language objective
        5. input_mutation_hints — for address-finding tasks
        6. budget caps — max_gecko_runs, max_tool_calls, message_limit, run_seconds
        7. game context — ISO + savestates (on Task/Project, not here)
    """

    goal_type: GoalType
    capabilities: set[Capability]
    evaluation: EvaluationMethod = EvaluationMethod.MANUAL_REVIEW
    target_description: str = ""
    input_mutation_hints: list[InputMutationHint] = field(default_factory=list)

    # Budget caps
    max_gecko_runs: int = 10
    max_tool_calls: int = 500
    message_limit: int = 200
    run_seconds: int = 10

    # HUD-specific scoring thresholds (only for pixel_diff_mask)
    hud_min_mean: float = 5.0
    preserve_max_mean: float = 6.0

    def validate(self) -> list[str]:
        """Return constraint violation messages. Empty = valid."""
        errors: list[str] = []
        if self.goal_type == GoalType.FIND_RAM_ADDRESS and Capability.RAM_POKE not in self.capabilities:
            errors.append("find_ram_address requires ram_poke capability")
        if self.goal_type == GoalType.FIND_CODE_PATCH and Capability.GECKO_INJECTION not in self.capabilities:
            errors.append("find_code_patch requires gecko_injection capability")
        if self.goal_type == GoalType.STATIC_RESEARCH and Capability.STATIC_RE not in self.capabilities:
            errors.append("static_research requires static_re capability")
        if Capability.PIXEL_DIFF in self.capabilities and Capability.FRAME_CAPTURE not in self.capabilities:
            errors.append("pixel_diff requires frame_capture capability")
        if self.evaluation == EvaluationMethod.PIXEL_DIFF_MASK:
            if Capability.PIXEL_DIFF not in self.capabilities:
                errors.append("pixel_diff_mask evaluation requires pixel_diff capability")
        return errors

    @property
    def needs_savestate(self) -> bool:
        """True if any runtime capability is enabled."""
        runtime_caps = {
            Capability.GECKO_INJECTION,
            Capability.RAM_POKE,
            Capability.INPUT_INJECTION,
            Capability.FRAME_CAPTURE,
        }
        return bool(self.capabilities & runtime_caps)

    @property
    def needs_mask(self) -> bool:
        return self.evaluation == EvaluationMethod.PIXEL_DIFF_MASK

    @property
    def needs_dolphin_session(self) -> bool:
        """True if a persistent Dolphin session is needed (RAM/input tools)."""
        return Capability.RAM_POKE in self.capabilities or Capability.INPUT_INJECTION in self.capabilities

    @property
    def uses_visual_gecko(self) -> bool:
        """True if Gecko injection uses the pixel-diff feedback loop (run_gecko tool)."""
        return (
            Capability.GECKO_INJECTION in self.capabilities
            and self.evaluation == EvaluationMethod.PIXEL_DIFF_MASK
        )

    @property
    def uses_interactive_gecko(self) -> bool:
        """True if Gecko injection uses the interactive apply+inspect loop."""
        return (
            Capability.GECKO_INJECTION in self.capabilities
            and self.evaluation != EvaluationMethod.PIXEL_DIFF_MASK
        )

    # ── Serialization ──────────────────────────────────────────────── #

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        d = asdict(self)
        d["goal_type"] = self.goal_type.value
        d["capabilities"] = sorted(c.value for c in self.capabilities)
        d["evaluation"] = self.evaluation.value
        d["input_mutation_hints"] = [asdict(h) for h in self.input_mutation_hints]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> JobSpec:
        """Deserialize from dict (e.g. JSON-loaded TaskConfig)."""
        return cls(
            goal_type=GoalType(d["goal_type"]),
            capabilities={Capability(c) for c in d.get("capabilities", [])},
            evaluation=EvaluationMethod(d.get("evaluation", "manual_review").replace("none", "manual_review")),
            target_description=d.get("target_description", ""),
            input_mutation_hints=[
                InputMutationHint(**h) for h in d.get("input_mutation_hints", [])
            ],
            max_gecko_runs=d.get("max_gecko_runs", 10),
            max_tool_calls=d.get("max_tool_calls", 500),
            message_limit=d.get("message_limit", 200),
            run_seconds=d.get("run_seconds", 10),
            hud_min_mean=d.get("hud_min_mean", 5.0),
            preserve_max_mean=d.get("preserve_max_mean", 6.0),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, text: str) -> JobSpec:
        return cls.from_dict(json.loads(text))
