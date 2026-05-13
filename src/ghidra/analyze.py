"""Headless Ghidra runner via PyGhidra.

PyGhidra lets us drive Ghidra's Java API directly from Python 3, no
subprocess / postScript dance. We import the DOL, run auto-analysis,
walk every function, decompile each, and write a JSON index plus a
per-function pseudocode file.

The Ghidra install path must be in `SPECTRE_GHIDRA_HOME`. PyGhidra
discovers it via the standard `GHIDRA_INSTALL_DIR` env var, so we
mirror it into the subprocess env before `pyghidra.start()`.

GameCubeLoader (community extension; ships in the user's Ghidra
install) handles DOL section mapping automatically. Its only headless
gotcha is an interactive "load a symbol map?" prompt; we satisfy it by
dropping an empty `<dolname>.map` next to the DOL.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from src.logging import logger


@dataclass(frozen=True)
class AnalysisResult:
    cache_dir: Path
    project_dir: Path
    dol_sha1: str
    function_count: int


def _resolve_ghidra_home() -> Path:
    raw = os.environ.get("SPECTRE_GHIDRA_HOME")
    if not raw:
        raise RuntimeError("SPECTRE_GHIDRA_HOME not set (path to a Ghidra install)")
    home = Path(raw).expanduser().resolve()
    if not (home / "support" / "analyzeHeadless").exists():
        raise FileNotFoundError(f"not a Ghidra install root: {home}")
    return home


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_elf(path: Path) -> bool:
    with path.open("rb") as f:
        return f.read(4) == b"\x7fELF"


def _ensure_empty_map(binary_path: Path) -> None:
    """Create an empty `<binary>.map` if missing — only relevant for DOLs.

    GameCubeLoader prompts for a symbol map at load time when its auto
    discovery finds nothing. An empty map satisfies "something was found"
    and skips the GUI dialog (which fatally fails in headless mode). ELFs
    use Ghidra's stock ElfLoader and don't need this workaround.
    """
    if _is_elf(binary_path):
        return
    map_path = binary_path.with_suffix(".map")
    if not map_path.exists():
        map_path.write_text("")


def run_analysis(
    binary_path: Path,
    cache_dir: Path,
    *,
    project_name: str = "spectre",
    force: bool = False,
) -> AnalysisResult:
    """Analyze `binary_path` (ELF or DOL) and dump the cache."""
    home = _resolve_ghidra_home()
    os.environ["GHIDRA_INSTALL_DIR"] = str(home)

    binary_path = binary_path.resolve()
    cache_dir = cache_dir.resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    decomp_dir = cache_dir / "decompiled"
    decomp_dir.mkdir(exist_ok=True)

    _ensure_empty_map(binary_path)

    binary_sha1 = _sha1(binary_path)
    sentinel = cache_dir / ".binary_sha1"
    legacy_sentinel = cache_dir / ".dol_sha1"  # back-compat
    if not force and sentinel.exists() and sentinel.read_text().strip() == binary_sha1:
        existing = list(decomp_dir.glob("*.txt"))
        logger.info("analysis_cache_hit", sha1=binary_sha1, functions=len(existing))
        return AnalysisResult(
            cache_dir=cache_dir,
            project_dir=cache_dir / "_project",
            dol_sha1=binary_sha1,
            function_count=len(existing),
        )
    if legacy_sentinel.exists():
        legacy_sentinel.unlink()

    project_dir = cache_dir / "_project"
    if project_dir.exists():
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True)

    logger.info("analysis_start", binary=str(binary_path), cache=str(cache_dir))
    n = _run_pyghidra(
        binary_path,
        project_dir,
        project_name,
        decomp_dir,
        functions_json=cache_dir / "functions.json",
        callgraph_json=cache_dir / "callgraph.json",
        strings_json=cache_dir / "strings.json",
        entry_points_json=cache_dir / "entry_points.json",
    )
    sentinel.write_text(binary_sha1)
    logger.info("analysis_done", sha1=binary_sha1, functions=n)
    return AnalysisResult(
        cache_dir=cache_dir,
        project_dir=project_dir,
        dol_sha1=binary_sha1,
        function_count=n,
    )


def _run_pyghidra(
    binary_path: Path,
    project_dir: Path,
    project_name: str,
    decomp_dir: Path,
    *,
    functions_json: Path,
    callgraph_json: Path,
    strings_json: Path,
    entry_points_json: Path,
) -> int:
    # Lazy import — pyghidra.start() spins up the JVM, slow on first call.
    import pyghidra

    pyghidra.start()

    from ghidra.app.decompiler import DecompInterface
    from ghidra.util.task import ConsoleTaskMonitor

    with pyghidra.open_program(
        binary_path,
        project_location=str(project_dir),
        project_name=project_name,
        analyze=True,
    ) as flat_api:
        program = flat_api.getCurrentProgram()
        listing = program.getListing()
        funcs = list(program.getFunctionManager().getFunctions(True))

        decompiler = DecompInterface()
        decompiler.openProgram(program)
        monitor = ConsoleTaskMonitor()

        entries: list[dict[str, str | int]] = []
        callgraph: dict[str, dict[str, list[dict[str, object]] | list[str]]] = {}

        # Build a quick addr → name map up-front (used to label callees/callers
        # with whatever Ghidra auto-named them at analysis time).
        name_by_addr = {f"{int(f.getEntryPoint().getOffset()):08x}": str(f.getName()) for f in funcs}

        for f in funcs:
            addr = int(f.getEntryPoint().getOffset())
            name = str(f.getName())
            size = int(f.getBody().getNumAddresses())
            addr_hex = f"{addr:08x}"
            entries.append({"addr": addr_hex, "name": name, "size": size})

            callees: list[dict[str, object]] = []
            for callee in f.getCalledFunctions(monitor):
                c_addr = f"{int(callee.getEntryPoint().getOffset()):08x}"
                callees.append({"addr": c_addr, "name": str(callee.getName())})

            callers: list[str] = []
            for caller in f.getCallingFunctions(monitor):
                callers.append(f"{int(caller.getEntryPoint().getOffset()):08x}")

            callgraph[addr_hex] = {"callees": callees, "callers": callers}

            try:
                res = decompiler.decompileFunction(f, 60, monitor)
                if res is not None and res.decompileCompleted():
                    code = str(res.getDecompiledFunction().getC())
                else:
                    msg = res.getErrorMessage() if res is not None else "no result"
                    code = f"// decompile failed: {msg}\n"
            except Exception as exc:  # noqa: BLE001 — keep one bad func from killing the run
                code = f"// decompile exception: {exc}\n"

            (decomp_dir / f"{addr_hex}.txt").write_text(code)

        decompiler.dispose()

        functions_json.write_text(json.dumps({"functions": entries}, indent=2))
        callgraph_json.write_text(json.dumps(callgraph, indent=2))

        # Defined strings + xrefs into them. We tag each xref with the
        # containing function (if any) so the agent can jump straight from
        # a string hit to a code site.
        strings_out: list[dict[str, object]] = []
        ref_mgr = program.getReferenceManager()
        fm = program.getFunctionManager()
        for data in listing.getDefinedData(True):
            dt = data.getDataType()
            type_name = str(dt.getName()).lower()
            if "string" not in type_name and "char" not in type_name:
                continue
            try:
                value = data.getValue()
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(value, str) or not value:
                continue
            text = value[:160]
            saddr = int(data.getAddress().getOffset())
            xrefs_to: list[str] = []
            for ref in ref_mgr.getReferencesTo(data.getAddress()):
                from_addr = ref.getFromAddress()
                fn = fm.getFunctionContaining(from_addr)
                if fn is not None:
                    xrefs_to.append(f"{int(fn.getEntryPoint().getOffset()):08x}")
            if not xrefs_to:
                # Skip strings nobody references — noise, lots of them in ELFs.
                continue
            # Dedupe while preserving order.
            seen: set[str] = set()
            uniq = []
            for x in xrefs_to:
                if x not in seen:
                    seen.add(x)
                    uniq.append(x)
            strings_out.append({"addr": f"{saddr:08x}", "text": text, "xrefs": uniq})
        strings_json.write_text(json.dumps({"strings": strings_out}, indent=2))

        # Entry points = anywhere the loader marked external entry, plus the
        # symbol-table entry if defined.
        entry_addrs: list[str] = []
        for ep in program.getSymbolTable().getExternalEntryPointIterator():
            ep_hex = f"{int(ep.getOffset()):08x}"
            entry_addrs.append(ep_hex)
        entry_points_json.write_text(
            json.dumps(
                {
                    "entries": [
                        {"addr": a, "name": name_by_addr.get(a, "<unmapped>")}
                        for a in entry_addrs
                    ],
                },
                indent=2,
            )
        )

        return len(entries)
