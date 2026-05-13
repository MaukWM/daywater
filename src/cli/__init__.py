"""Thin argparse CLIs over `src.dolphin` library.

The library functions are the source of truth; these wrappers only handle
arg parsing, path resolution, and human-readable stdout. Inspect AI tools
will call the library directly, not these scripts.
"""
