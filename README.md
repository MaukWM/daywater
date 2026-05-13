# spectre

Automatically find scene-manipulation Gecko cheats (HUD removal, freecam,
noclip) for GameCube games. Given a ROM, a reference frame, and a HUD
mask, the agent iterates Gecko candidates against a Dolphin verifier until
the masked regions go quiet without breaking the rest of the scene.

## Setup

Requires Python 3.13+, [uv](https://docs.astral.sh/uv/), and Dolphin at
`/Applications/Dolphin.app` (macOS dev path).

```bash
uv sync
uv run pre-commit install
cp .env.example .env
```

## CLI

Two entry points are installed by `uv sync`:

```bash
# boot Dolphin once, dump frames
uv run spectre-probe --iso PATH --savestate PATH [--gecko PATH] --out DIR --run-seconds N

# pixel-diff two frame-dump directories
uv run spectre-diff --a DIR --b DIR [--frames last|all|N,N,...]
```

Flags: `spectre-probe --help`, `spectre-diff --help`.

## Smoke test (Nightfire NTSC)

You need a Nightfire NTSC ISO (game ID `GO7E69`) and a Dolphin `.s##` save
state with the in-game scene loaded. Stash the paths somewhere convenient:

```bash
export ISO=/path/to/nightfire.iso
export SAV=/path/to/GO7E69.s01

uv run spectre-probe --iso "$ISO" --savestate "$SAV" --out /tmp/sp_base  --run-seconds 10
uv run spectre-probe --iso "$ISO" --savestate "$SAV" --out /tmp/sp_nohud --run-seconds 10 \
  --gecko cheats/nightfire_nohud.gecko

uv run spectre-diff --a /tmp/sp_base/frames --b /tmp/sp_nohud/frames --frames all
```

Expected: `compass_bl` and `ammo_br` mean Δ ≥ 5, `center_no_hud` near 0.

## Dev

```bash
uv run pre-commit run --all-files
uv run pytest
uv run mypy src/
uv run ruff check src/ tests/
```

Configuration via env vars — see `.env.example`.

## Quirks

- Dolphin window flashes briefly on macOS even with hidden launch — cosmetic.
- Save states are not portable across Dolphin versions; pin one build.
- Linux verifier container needs `docker run --shm-size=2g` (Dolphin
  MemArena exceeds the default 64 MB `/dev/shm`).

See `../docs/dolphin-emulation-walkthrough.md` for the full Dolphin
gotcha list and `local_docs/PROGRESS.md` for the build log.
