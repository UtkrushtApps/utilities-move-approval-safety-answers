from __future__ import annotations

from agent.schemas import DecisionAction, MoveDecision, PendingMove


class PolicyViolation(ValueError):
    """Raised when an interpreted action is not safe to execute."""


def proposal_requires_approval(decision: MoveDecision) -> bool:
    """Return true for every interpreted irreversible closure proposal."""
    return decision.action == DecisionAction.PROPOSE_CLOSE


def approval_matches_pending(
    message: str,
    decision: MoveDecision,
    pending: PendingMove | None,
) -> bool:
    """Validate an approval against the exact durable proposal.

    The model's bounded interpretation is used instead of parsing customer prose.
    A deictic confirmation may omit both fields and therefore refers to the stored
    details. If the model extracted either field, it must equal the stored value.
    Cancelled proposals and unrelated actions are never executable.
    """
    del message

    if decision.action != DecisionAction.CONFIRM or pending is None:
        return False
    if pending.state not in {"awaiting", "executing", "completed"}:
        return False
    if decision.account_id is not None and decision.account_id != pending.account_id:
        return False
    if decision.stop_date is not None and decision.stop_date != pending.stop_date:
        return False
    return True


def render_confirmation(pending: PendingMove) -> str:
    return (
        f"Please confirm closing {pending.account_id} on "
        f"{pending.stop_date.isoformat()}."
    )
