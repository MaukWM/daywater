"""Strategy blocks for static_research tasks."""

STRATEGY = """\
## Your approach

1. **Start with `list_research()` and `list_findings()`** to see what \
   prior tasks have already discovered. Don't redo work.
2. **Stay focused on the research question** in the task description. \
   Don't map the entire binary — go deep on the specific system asked about.
3. **Document as you go** — use `rename_function` and `add_note` for \
   binary-level annotations, `save_finding` for structured discoveries, \
   and `write_research` for narrative documentation.

## When you're done

Before submitting your final answer, **document what you learned**:

1. **Save structured findings** via `save_finding` — every function \
   you identified (kind="function"), memory addresses (kind="address"), \
   and key observations (kind="note").
2. **Write a research doc** via `write_research(filename, content, summary)` \
   — a document summarizing your analysis: what you explored, what the \
   call graph looks like, what you tried and why it worked or didn't, \
   and what questions remain. Include a one-line summary for the index.

Then call `submit()` with a concise summary of your key discoveries. \
This ends the task. The summary should highlight what you found, what \
addresses/functions are important, and what questions remain for \
future research."""
