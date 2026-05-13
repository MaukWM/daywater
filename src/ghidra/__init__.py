"""Ghidra-backed static analysis for spectre."""

from src.ghidra.analyze import run_analysis
from src.ghidra.cache import (
    callees_of,
    callers_of,
    find_functions,
    load_entry_points,
    load_function_index,
    read_decompiled,
    resolve_function,
    search_strings,
)
from src.ghidra.dol import extract_dol
from src.ghidra.notes import NotesStore

__all__ = [
    "NotesStore",
    "callees_of",
    "callers_of",
    "extract_dol",
    "find_functions",
    "load_entry_points",
    "load_function_index",
    "read_decompiled",
    "resolve_function",
    "run_analysis",
    "search_strings",
]
