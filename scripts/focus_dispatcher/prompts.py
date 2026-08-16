"""Prompt and contract generation."""
from .state import incomplete_subtasks


def generate_prompt(title, item, source):
    label = item.get("label", "Unknown")
    text = item.get("text", "")
    branch = item.get("branch")
    subtasks = item.get("subtasks", [])

    lines = [
        f"# NEXT FOCUS: {label}",
        "",
        f"**Section:** {title}",
        "",
        f"**Branch:** {branch or 'shared'}",
        "",
        f"**Priority:** {item.get('priority', 'medium')}",
        "",
        "## Description",
        "",
        text.strip() if isinstance(text, str) and text.strip() else "(no description)",
        "",
        "## Incomplete subtasks",
        "",
    ]
    incomplete = incomplete_subtasks(item)
    if incomplete:
        for st in incomplete:
            lines.append(f"- [ ] {st.get('label', st)}")
    else:
        lines.append("- No tracked subtasks")
    lines.append("")
    if subtasks:
        lines.append("## All subtasks")
        lines.append("")
        for st in subtasks:
            mark = "x" if st.get("status") == "completed" else " "
            lines.append(f"- [{mark}] {st.get('label', st)}")
        lines.append("")

    if source:
        lines.append(f"**Source:** {source}")
        lines.append("")

    lines.append("## Instructions for the assistant")
    lines.append("")
    lines.append("1. Work only inside this focus unless the user asks otherwise.")
    lines.append("2. Mark each subtask completed in `docs/ssot/ssot.focus.current.yml` as you finish it.")
    lines.append("3. When the focus is complete, update `docs/ssot/ssot.focus.yml` history and run the focus-dispatcher again.")
    lines.append("")

    return "\n".join(lines)


def generate_suggestion_prompt(item):
    label = item.get("label", "Unknown")
    text = item.get("text", "")
    lines = [
        "# NO ACTIVE FOCUS — SUGGESTED BACKLOG ITEM",
        "",
        f"**Suggested:** {label}",
        f"**Priority:** {item.get('priority', 'medium')}",
        "",
        "## Description",
        "",
        text.strip() if isinstance(text, str) and text.strip() else "(no description)",
        "",
        "## Instructions",
        "1. This item is in the Backlog - Triage Queue; it is NOT activated.",
        "2. To activate it, run `python3 scripts/focus-dispatcher.py --inbox <path>` or update `ssot.focus.current.yml` manually.",
        "3. Otherwise, continue with any active focus or quick win.",
    ]
    return "\n".join(lines)


def generate_subagent_contract(title, item, source):
    prompt = generate_prompt(title, item, source)
    notes = [
        "",
        "## Sub-agent contract",
        "",
        "- This focus is delegated to a background sub-agent.",
        "- The sub-agent should not ask clarifying questions; make reasonable assumptions and proceed.",
        "- Mark subtasks completed in `docs/ssot/ssot.focus.current.yml` as you finish them.",
        "- Do not commit or push; the main session will review the diff and commit.",
        "- If a task requires destructive changes, stop and ask for confirmation.",
        "- Run py_compile / validation before finishing.",
    ]
    return prompt + "\n".join(notes)
