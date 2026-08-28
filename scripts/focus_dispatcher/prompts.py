"""Prompt and contract generation."""
from .state import incomplete_subtasks


def generate_prompt(title, item, source):
    label = item.get("label", "Unknown")
    text = item.get("text", "")
    branch = item.get("branch")
    subtasks = item.get("subtasks", [])

    ownership = item.get("ownership") or {}
    lines = [
        f"# NEXT FOCUS: {label}",
        "",
        f"**Section:** {title}",
        "",
        f"**Branch:** {branch or 'shared'}",
        "",
        f"**Priority:** {item.get('priority', 'medium')}",
        "",
    ]
    if ownership:
        lines.append(f"**Owner:** {ownership.get('owner', 'tony')}")
        lines.append(f"**Session:** {ownership.get('session', '')}")
        lines.append(f"**Locked:** {ownership.get('locked', False)}")
        if ownership.get('lock_reason'):
            lines.append(f"**Lock reason:** {ownership.get('lock_reason')}")
        lines.append("")
    if item.get("safe_to_parallel"):
        lines.append("**Safe to run in parallel:** yes")
        lines.append("")
    lines.extend([
        "## Description",
        "",
        text.strip() if isinstance(text, str) and text.strip() else "(no description)",
        "",
        "## Incomplete subtasks",
        "",
    ])
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
    subagent = item.get("subagent", {})
    ownership = item.get("ownership") or {}
    safe = item.get("safe_to_parallel", False)
    if subagent:
        profile = subagent.get("profile", "subagent_general")
        parallel = subagent.get("parallel", False)
        requires_approval = subagent.get("requires_approval", False)
        can_change_host = subagent.get("can_change_host", False)
        notes = subagent.get("notes", "")
        contract = [
            "",
            "## Sub-agent contract",
            "",
        ]
        if safe:
            contract.extend([
                "- This focus is safe to run in parallel with the active focus.",
                f"- Safe to parallel: {safe}",
            ])
        if ownership:
            contract.append(f"- Owner: {ownership.get('owner', 'tony')} | Session: {ownership.get('session', '')} | Locked: {ownership.get('locked', False)}")
        contract.extend([
            f"- This focus is delegated to a background sub-agent.",
            f"- Profile: `{profile}`",
            f"- Parallel: {parallel}",
            f"- Requires approval before destructive changes: {requires_approval}",
            f"- Can change host: {can_change_host}",
        ])
        if notes:
            contract.extend([f"- Notes: {notes}", ""])
        contract.extend([
            "- The sub-agent should not ask clarifying questions; make reasonable assumptions and proceed.",
            "- Mark subtasks completed in `docs/ssot/ssot.focus.current.yml` as you finish them.",
            "- Do not commit or push; the main session will review the diff and commit.",
            "- If a task requires destructive changes, stop and ask for confirmation.",
            "- Run py_compile / validation before finishing.",
        ])
    else:
        contract = [
            "",
            "## Sub-agent contract",
            "",
            "- This focus is delegated to a background sub-agent.",
            "- The sub-agent should not ask clarifying questions; make reasonable assumptions and proceed.",
            "- Mark subtasks completed in `docs/ssot/ssot.focus.current.yml` as you finish it.",
            "- Do not commit or push; the main session will review the diff and commit.",
            "- If a task requires destructive changes, stop and ask for confirmation.",
            "- Run py_compile / validation before finishing.",
        ]
    return prompt + "\n".join(contract)
