"""Single source for the card-judgment authority rule — mirrors
ada-voice backend/tools.d/kanban.py _card_gates(). Change the TOOL
first, then update this file and rebuild corpus.jsonl — corpus labels
and the scorer prompt both derive from here (ADA-1128)."""
import re

PRODSEC_RE = re.compile(r"(?i)prod|security|infra|deploy")

GATED_SUMMARY = ("priority:high, review_kind:decide, or "
                 "prod/security-tagged cards")


def close_gate(card: dict) -> str | None:
    """Why closing/executing on this card is gated for Ada — the same
    reasons _card_gates returns. None = her free authority covers it."""
    gated = []
    if str(card.get("priority") or "").lower() == "high":
        gated.append("priority:high")
    if str(card.get("review_kind") or "").lower() == "decide":
        gated.append("review_kind:decide")
    if any(PRODSEC_RE.search(str(t)) for t in (card.get("tags") or [])):
        gated.append("prod/security tag")
    return ", ".join(gated) or None
