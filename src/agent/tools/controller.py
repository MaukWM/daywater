"""Controller input and position sampling tools.

Tools: press_button, set_stick, wait, sample_position.
Constants: GC_BUTTONS, GC_STICKS.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from inspect_ai.tool import Tool, tool

from src.core.dolphin.input import InputCommand, InputSequence

if TYPE_CHECKING:
    from src.core.dolphin.session import DolphinSession

# Valid GC buttons for the pipe protocol.
GC_BUTTONS = frozenset(
    {
        "A",
        "B",
        "X",
        "Y",
        "Z",
        "START",
        "L",
        "R",
        "D_UP",
        "D_DOWN",
        "D_LEFT",
        "D_RIGHT",
    }
)

# Valid stick names.
GC_STICKS = frozenset({"MAIN", "C"})


# ── Input tools (raw GC controller) ───────────────────────────────────── #


@tool
def press_button(session: DolphinSession) -> Tool:
    """Build a button press tool bound to a DolphinSession."""

    async def execute(button: str, duration: float = 0.3) -> str:
        """Press a GameCube controller button for a duration, then release.

        Args:
            button: Button name. One of: A, B, X, Y, Z, START, L, R,
                D_UP, D_DOWN, D_LEFT, D_RIGHT.
            duration: How long to hold the button in seconds (default: 0.3).
        """
        btn = button.upper().strip()
        if btn not in GC_BUTTONS:
            return f"Error: unknown button '{btn}'. Valid: {', '.join(sorted(GC_BUTTONS))}"
        if duration > 15.0:
            return "Error: duration capped at 15 seconds."
        if duration < 0.05:
            return "Error: duration must be at least 0.05 seconds."

        seq = InputSequence(
            commands=[
                InputCommand(0.0, f"PRESS {btn}"),
                InputCommand(duration, f"RELEASE {btn}"),
            ]
        )
        try:
            session.play_sequence(seq)
        except Exception as e:
            return f"Error: {e}"

        return f"Pressed {btn} for {duration:.2f}s."

    return execute


@tool
def set_stick(session: DolphinSession) -> Tool:
    """Build a stick position tool bound to a DolphinSession."""

    async def execute(
        stick: str = "MAIN",
        x: float = 0.5,
        y: float = 0.5,
        duration: float = 3.0,
    ) -> str:
        """Hold a GameCube analog stick at a position, then return to neutral.

        The stick axes range from 0.0 to 1.0, where 0.5 is neutral (center).

        For the MAIN stick:
          - x=0.0 is full left, x=1.0 is full right
          - y=0.0 is full up/forward, y=1.0 is full down/backward

        For the C stick (camera):
          - Same axis mapping as MAIN

        Args:
            stick: "MAIN" for the main analog stick, "C" for the C-stick.
            x: Horizontal position 0.0–1.0 (0.5 = neutral).
            y: Vertical position 0.0–1.0 (0.5 = neutral).
            duration: How long to hold this position in seconds (default: 3.0).
        """
        stick_name = stick.upper().strip()
        if stick_name not in GC_STICKS:
            return f"Error: unknown stick '{stick_name}'. Valid: MAIN, C"
        if duration > 15.0:
            return "Error: duration capped at 15 seconds."
        if duration < 0.1:
            return "Error: duration must be at least 0.1 seconds."
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            return "Error: x and y must be in range 0.0–1.0."

        seq = InputSequence(
            commands=[
                InputCommand(0.0, f"SET {stick_name} {x:.3f} {y:.3f}"),
                InputCommand(duration, f"SET {stick_name} 0.500 0.500"),
            ]
        )
        try:
            session.play_sequence(seq)
        except Exception as e:
            return f"Error: {e}"

        return f"Held {stick_name} stick at ({x:.2f}, {y:.2f}) for {duration:.1f}s."

    return execute


@tool
def wait(session: DolphinSession) -> Tool:
    """Build a wait tool (let the game run with no input)."""

    async def execute(duration: float = 2.0) -> str:
        """Wait for a duration with no controller input. The game continues running.

        Useful to let physics settle after movement, or to observe values at rest.

        Args:
            duration: How long to wait in seconds (default: 2.0).
        """
        if duration > 30.0:
            return "Error: duration capped at 30 seconds."
        if duration < 0.1:
            return "Error: duration must be at least 0.1 seconds."

        time.sleep(duration)
        return f"Waited {duration:.1f}s."

    return execute


# ── Position sampling tool ────────────────────────────────────────────── #


@tool
def sample_position(session: DolphinSession) -> Tool:
    """Build a position sampling tool bound to a DolphinSession."""

    async def execute(
        x_addr: str,
        y_addr: str,
        z_addr: str,
        duration: float = 3.0,
        interval: float = 0.5,
    ) -> str:
        """Poll three memory addresses over time to observe their trajectory.

        Use this to verify candidate position addresses: send input first,
        then sample during movement to see if the values track position.

        Args:
            x_addr: Hex address for X coordinate.
            y_addr: Hex address for Y coordinate.
            z_addr: Hex address for Z coordinate.
            duration: How long to sample in seconds (default: 3.0).
            interval: Polling interval in seconds (default: 0.5).
        """
        try:
            x = int(x_addr, 16)
            y = int(y_addr, 16)
            z = int(z_addr, 16)
        except ValueError:
            return "Error: addresses must be hex."

        if duration > 15.0:
            return "Error: duration capped at 15 seconds."

        samples = session.sample_position_over_time(x, y, z, duration, interval)

        if not samples:
            return "No samples collected — Dolphin may not be running."

        lines = [f"Sampled {len(samples)} points over {duration:.1f}s:"]
        lines.append(f"  {'Time':>6}  {'X':>12}  {'Y':>12}  {'Z':>12}")
        for s in samples:
            lines.append(f"  {s.timestamp:6.2f}  {s.x:12.4f}  {s.y:12.4f}  {s.z:12.4f}")

        # Summary: total displacement
        if len(samples) >= 2:
            dx = samples[-1].x - samples[0].x
            dy = samples[-1].y - samples[0].y
            dz = samples[-1].z - samples[0].z
            lines.append(f"\nTotal displacement: dX={dx:+.4f} dY={dy:+.4f} dZ={dz:+.4f}")

        return "\n".join(lines)

    return execute
