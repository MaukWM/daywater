"""Strategy blocks for find_ram_address tasks (position, health, ammo, etc.)."""

STRATEGY = """\
## Strategy — find RAM addresses

**Important**: Many games store data in multiple places — the player \
object, camera slots, HUD/radar caches, physics mirrors. You must find \
the PRIMARY source where the value is computed and written, not a \
downstream copy. Confirm via write watchpoints and decompiling the \
writing code.

### Step 1: Read prior knowledge

Call `list_research()`, `list_findings()`, and `list_savestate_findings()` \
to see what earlier tasks discovered. Research docs may already identify \
struct offsets and name the relevant functions.

### Step 2: Find candidate addresses

Use `scan_memory_diff()` to capture a baseline, then perform the expected \
input (see input-mutation hints in the task description), then diff again. \
Look for addresses that changed by a plausible delta.

If prior research identifies struct offsets and global pointer tables, \
you can also dereference pointers with `read_memory` to calculate offsets.

### Step 3: Verify with write watchpoints (REQUIRED)

For each candidate address, call `find_writers(address, duration=3.0)` \
while performing the relevant input. This returns the PC of every \
instruction that writes to that address.

Then **decompile each writing PC**. You need to determine:
- Is this the primary update function? (authoritative — GOOD)
- Is this a sync/copy from somewhere else? (copy — BAD)
- Is this a HUD/radar/minimap cache? (copy — BAD)
- Is this an interpolation/rendering buffer? (copy — BAD)

The authoritative address is the one written by the primary update \
function.

### Step 4: Distinguish values

Verify which address corresponds to which concept by observing how \
different inputs affect different addresses (see input-mutation hints).

Use `sample_position` or `read_memory_batch` to observe trajectories.

### Step 5: Save findings

Save the verified addresses as savestate findings. Each finding MUST \
include in the detail field:
- The writing PC(s) and function name
- Why this is the authoritative source (not a copy)
- How you confirmed the mapping

### Step 6: Submit

Call `submit()` with a summary of the addresses, the authoritative \
writing function(s), and any copy addresses you identified and ruled out.

## Important notes

- The game is already running from a savestate. Do NOT try to boot Dolphin.
- Memory addresses are specific to this savestate's memory layout.
- There will be MULTIPLE addresses that track the same value. Your job is \
  to find the primary/authoritative one and explain why it's not a copy.
- Write watchpoints briefly pause the game. Keep durations short (2-3s) \
  and send input before/during so writes happen.
- If `find_writers` returns no hits, the address may only be written \
  during specific actions — try sending input first, then monitoring."""
