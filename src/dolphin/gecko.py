"""Gecko code parsing + Dolphin per-game INI rendering.

Gecko text input format (extensible, single block):

    $DisableHUD
    04066570 4800006C
    $Unnamed
    XXXXXXXX YYYYYYYY

`#` and blank lines are ignored. A `$Name` line opens a code; subsequent
non-comment lines are the code body (one or more 16-char hex pairs).

Dolphin loads Gecko codes from `<UserDir>/GameSettings/<GameID>.ini`. We
render two sections: `[Gecko_Enabled]` listing enabled `$Name`s and
`[Gecko]` carrying each code's name + body lines.

Pure functions, no I/O. Caller writes the rendered text to disk.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GeckoCode:
    """One named Gecko code: `$name` plus 16-char-hex body lines."""

    name: str
    lines: tuple[str, ...]


def parse_gecko(text: str) -> list[GeckoCode]:
    """Parse `$Name` / hex-pair blocks. Empty input → empty list."""
    codes: list[GeckoCode] = []
    current_name: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        if current_name is not None:
            codes.append(GeckoCode(name=current_name, lines=tuple(current_lines)))

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("$"):
            flush()
            current_name = line[1:].strip() or "Unnamed"
            current_lines = []
        else:
            current_lines.append(line)
    flush()
    return codes


def render_gecko_ini(codes: list[GeckoCode]) -> str:
    """Render a list of codes as Dolphin per-game INI text.

    Empty input returns an empty string (caller should skip writing the file).
    """
    if not codes:
        return ""
    enabled_lines = [f"${c.name}" for c in codes]
    body_lines: list[str] = []
    for code in codes:
        body_lines.append(f"${code.name}")
        body_lines.extend(code.lines)
    return (
        "[Gecko_Enabled]\n"
        + "\n".join(enabled_lines)
        + "\n\n[Gecko]\n"
        + "\n".join(body_lines)
        + "\n"
    )
