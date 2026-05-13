#!/usr/bin/env bash
set -euo pipefail

ISO="${ISO:-/home/dolphin/iso/game.iso}"
SAVESTATE="${SAVESTATE:-}"
OUTDIR="${OUTDIR:-/out}"
RUN_SECONDS="${RUN_SECONDS:-30}"

if [[ ! -f "$ISO" ]]; then
  echo "ERROR: ISO not found at $ISO" >&2
  exit 1
fi

mkdir -p "$OUTDIR"

DUMP_DIR=/home/dolphin/.local/share/dolphin-emu/Dump/Frames
mkdir -p "$DUMP_DIR"

CPUCORE="${CPUCORE:-4}"
ARGS=(
  --platform=headless
  --video_backend=Software
  --audio_emulation=HLE
  -C Dolphin.Core.EnableCheats=True
  -C Dolphin.Core.CPUCore="$CPUCORE"
  -C Dolphin.Core.Fastmem=False
  -C Dolphin.Core.CPUThread=False
  -C Dolphin.DSP.Backend=Null
  -C Dolphin.Movie.DumpFrames=True
  -C Dolphin.Movie.DumpFramesSilent=True
  -C Dolphin.Display.RenderToMain=False
  --exec="$ISO"
)
if [[ -n "$SAVESTATE" && -f "$SAVESTATE" ]]; then
  ARGS+=(--save_state="$SAVESTATE")
fi

echo "[probe] /usr/games/dolphin-emu-nogui ${ARGS[*]}"
echo "[probe] frame dump dir: $DUMP_DIR"
echo "[probe] runtime: ${RUN_SECONDS}s"

timeout "$RUN_SECONDS" /usr/games/dolphin-emu-nogui "${ARGS[@]}" || true

echo "[probe] collecting dump"
shopt -s nullglob
files=("$DUMP_DIR"/*)
if (( ${#files[@]} > 0 )); then
  cp -r "$DUMP_DIR"/. "$OUTDIR"/
  echo "[probe] copied ${#files[@]} files"
else
  echo "[probe] no frames dumped"
fi
ls -la "$OUTDIR"
