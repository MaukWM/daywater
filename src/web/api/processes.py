"""Process monitor routes — list and kill Dolphin processes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/api/processes")
async def list_processes() -> list[dict]:  # type: ignore[type-arg]
    """List running Dolphin processes with age and resource info."""
    import subprocess
    import time

    try:
        result = subprocess.run(
            ["ps", "-eo", "pid,etimes,rss,args"],
            capture_output=True, text=True, timeout=5,
        )
        processes = []
        for line in result.stdout.strip().splitlines()[1:]:  # skip header
            parts = line.strip().split(None, 3)
            if len(parts) < 4 or "dolphin-emu" not in parts[3]:
                continue
            pid = int(parts[0])
            age_secs = int(parts[1])
            rss_kb = int(parts[2])
            cmd = parts[3]
            # Extract savestate/user_dir from command
            user_dir = ""
            for arg in cmd.split():
                if arg.startswith("-u"):
                    user_dir = arg[2:]
            processes.append({
                "pid": pid,
                "age_seconds": age_secs,
                "age_human": f"{age_secs // 60}m {age_secs % 60}s" if age_secs >= 60 else f"{age_secs}s",
                "rss_mb": round(rss_kb / 1024, 1),
                "user_dir": user_dir,
            })
        return processes
    except Exception:
        return []


@router.post("/api/processes/{pid}/kill")
async def kill_process(pid: int) -> dict[str, bool]:
    """Kill a specific Dolphin process."""
    import subprocess

    # Safety: only kill dolphin-emu processes
    try:
        check = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True, text=True, timeout=5,
        )
        if "dolphin-emu" not in check.stdout:
            raise HTTPException(400, "Not a Dolphin process")
        subprocess.run(["kill", "-9", str(pid)], check=False, timeout=5)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/processes/kill-all")
async def kill_all_dolphins() -> dict:  # type: ignore[type-arg]
    """Kill all Dolphin processes."""
    import subprocess

    result = subprocess.run(
        ["pkill", "-9", "-f", "dolphin-emu-nogui"],
        check=False, timeout=5,
    )
    return {"ok": True}
