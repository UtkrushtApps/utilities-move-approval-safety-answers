from __future__ import annotations

import logging

from agent.model_client import ModelBoundary
from agent.policy import approval_matches_pending, render_confirmation
from agent.prompts import PROMPT_VERSION
from agent.schemas import AgentReply, AgentRequest, DecisionAction, PendingMove
from agent.state import (
    MoveStore,
    PendingStateConflict,
    SessionOwnershipError,
)
from agent.tools import CloseServiceTool, ToolFailure

logger = logging.getLogger(__name__)


class MoveAgent:
    def __init__(
        self,
        model: ModelBoundary,
        store: MoveStore,
        tool: CloseServiceTool,
    ) -> None:
        self.model = model
        self.store = store
        self.tool = tool

    @staticmethod
    def _completed_reply(pending: PendingMove) -> AgentReply:
        return AgentReply(
            message="Your service closure has been scheduled.",
            completed=True,
            account_id=pending.account_id,
            stop_date=pending.stop_date,
        )

    async def handle(self, request: AgentRequest) -> AgentReply:
        try:
            self.store.ensure_session(request.session_id, request.customer_id)
        except SessionOwnershipError:
            self.store.record_trace(
                request.session_id,
                "approval_rejected",
                {"request_id": request.request_id, "reason": "session_unavailable"},
            )
            return AgentReply(
                message="This move request cannot be used. Please start a new session.",
                escalated=True,
            )

        try:
            decision = await self.model.decide(request.message)
        except Exception:
            logger.exception("Move request interpretation failed")
            self.store.record_trace(
                request.session_id,
                "interpretation_failed",
                {"request_id": request.request_id, "prompt_version": PROMPT_VERSION},
            )
            return AgentReply(
                message="I could not safely interpret that request. Please try again.",
                escalated=True,
            )

        # Traces intentionally contain bounded decision metadata, never raw messages
        # or the model's free-form reply.
        self.store.record_trace(
            request.session_id,
            "interpretation",
            {
                "request_id": request.request_id,
                "action": decision.action.value,
                "has_account": decision.account_id is not None,
                "has_stop_date": decision.stop_date is not None,
                "prompt_version": PROMPT_VERSION,
            },
        )

        if decision.action == DecisionAction.PROPOSE_CLOSE:
            if decision.account_id is None or decision.stop_date is None:
                self.store.record_trace(
                    request.session_id,
                    "proposal_rejected",
                    {"request_id": request.request_id, "reason": "missing_details"},
                )
                return AgentReply(
                    message="Please provide the account and desired stop date."
                )

            if not self.store.account_belongs_to(
                decision.account_id, request.customer_id
            ):
                self.store.record_trace(
                    request.session_id,
                    "proposal_rejected",
                    {"request_id": request.request_id, "reason": "account_unavailable"},
                )
                return AgentReply(
                    message="A specialist must review this move request.",
                    escalated=True,
                )

            operation_key = self.store.operation_key(
                decision.account_id, decision.stop_date
            )
            if self.store.get_order_id(operation_key) is not None:
                replay = PendingMove(
                    session_id=request.session_id,
                    customer_id=request.customer_id,
                    account_id=decision.account_id,
                    stop_date=decision.stop_date,
                    state="completed",
                    revision=0,
                )
                self.store.record_trace(
                    request.session_id,
                    "execution_replay",
                    {"request_id": request.request_id, "outcome": "already_completed"},
                )
                return self._completed_reply(replay)

            try:
                pending = self.store.save_pending(
                    request.session_id,
                    request.customer_id,
                    decision.account_id,
                    decision.stop_date,
                )
            except PendingStateConflict:
                self.store.record_trace(
                    request.session_id,
                    "proposal_rejected",
                    {"request_id": request.request_id, "reason": "execution_in_progress"},
                )
                return AgentReply(
                    message="An approved move request is already being processed."
                )

            self.store.record_trace(
                request.session_id,
                "proposal_pending",
                {
                    "request_id": request.request_id,
                    "account_id": pending.account_id,
                    "stop_date": pending.stop_date.isoformat(),
                    "revision": pending.revision,
                },
            )
            return AgentReply(
                message=render_confirmation(pending),
                needs_confirmation=True,
                account_id=pending.account_id,
                stop_date=pending.stop_date,
            )

        if decision.action == DecisionAction.CONFIRM:
            pending = self.store.get_pending(
                request.session_id,
                request.customer_id,
            )
            if not approval_matches_pending(request.message, decision, pending):
                reason = "missing_or_stale_approval"
                if pending is not None and (
                    (decision.account_id is not None and decision.account_id != pending.account_id)
                    or (decision.stop_date is not None and decision.stop_date != pending.stop_date)
                ):
                    reason = "details_mismatch"
                self.store.record_trace(
                    request.session_id,
                    "approval_rejected",
                    {"request_id": request.request_id, "reason": reason},
                )
                return AgentReply(
                    message="There is no matching move request ready to approve."
                )

            assert pending is not None
            operation_key = self.store.operation_key(
                pending.account_id, pending.stop_date
            )

            if pending.state == "completed":
                self.store.record_trace(
                    request.session_id,
                    "approval_replay",
                    {"request_id": request.request_id, "outcome": "already_completed"},
                )
                return self._completed_reply(pending)

            # Reconcile a durable order if a prior worker stopped after the tool
            # succeeded but before the session state was marked completed.
            order_id = self.store.get_order_id(operation_key)
            if order_id is not None:
                self.store.mark_completed(request.session_id, pending.revision)
                self.store.complete_operation(operation_key)
                self.store.record_trace(
                    request.session_id,
                    "approval_replay",
                    {
                        "request_id": request.request_id,
                        "outcome": "reconciled_completed",
                        "order_id": order_id,
                    },
                )
                return self._completed_reply(pending)

            claimed = self.store.claim_pending(
                request.session_id,
                request.customer_id,
            )
            if claimed is None:
                current = self.store.get_pending(
                    request.session_id, request.customer_id
                )
                if current is not None and current.state == "completed":
                    self.store.record_trace(
                        request.session_id,
                        "approval_replay",
                        {
                            "request_id": request.request_id,
                            "outcome": "already_completed",
                        },
                    )
                    return self._completed_reply(current)
                self.store.record_trace(
                    request.session_id,
                    "approval_replay",
                    {"request_id": request.request_id, "outcome": "in_progress"},
                )
                return AgentReply(
                    message="The approved move request is already being processed.",
                    account_id=pending.account_id,
                    stop_date=pending.stop_date,
                )

            self.store.record_trace(
                request.session_id,
                "approval_accepted",
                {
                    "request_id": request.request_id,
                    "account_id": claimed.account_id,
                    "stop_date": claimed.stop_date.isoformat(),
                    "revision": claimed.revision,
                },
            )

            if not self.store.claim_operation(operation_key):
                order_id = self.store.get_order_id(operation_key)
                if order_id is not None:
                    self.store.mark_completed(request.session_id, claimed.revision)
                    self.store.record_trace(
                        request.session_id,
                        "execution_replay",
                        {
                            "request_id": request.request_id,
                            "outcome": "already_completed",
                            "order_id": order_id,
                        },
                    )
                    return self._completed_reply(claimed)

                self.store.record_trace(
                    request.session_id,
                    "execution_replay",
                    {"request_id": request.request_id, "outcome": "in_progress"},
                )
                return AgentReply(
                    message="The approved move request is already being processed.",
                    account_id=claimed.account_id,
                    stop_date=claimed.stop_date,
                )

            try:
                order_id = await self.tool.close_service_account(
                    customer_id=request.customer_id,
                    account_id=claimed.account_id,
                    stop_date=claimed.stop_date,
                    operation_key=operation_key,
                )
            except ToolFailure:
                self.store.release_operation(operation_key)
                self.store.release_pending(request.session_id, claimed.revision)
                self.store.record_trace(
                    request.session_id,
                    "execution_rejected",
                    {"request_id": request.request_id, "reason": "tool_rejected"},
                )
                return AgentReply(
                    message="A specialist must review this move request.",
                    escalated=True,
                    account_id=claimed.account_id,
                    stop_date=claimed.stop_date,
                )
            except Exception:
                logger.exception("Unexpected service closure failure")
                # Reconcile first: the tool may have durably succeeded before an
                # exception was observed by the caller.
                order_id = self.store.get_order_id(operation_key)
                if order_id is None:
                    self.store.release_operation(operation_key)
                    self.store.release_pending(request.session_id, claimed.revision)
                    self.store.record_trace(
                        request.session_id,
                        "execution_failed",
                        {"request_id": request.request_id, "reason": "unexpected_failure"},
                    )
                    return AgentReply(
                        message="The move request could not be safely completed.",
                        escalated=True,
                    )

            self.store.complete_operation(operation_key)
            self.store.mark_completed(request.session_id, claimed.revision)
            self.store.record_trace(
                request.session_id,
                "execution_completed",
                {"request_id": request.request_id, "order_id": order_id},
            )
            return self._completed_reply(claimed)

        if decision.action == DecisionAction.CANCEL:
            cancelled = self.store.cancel_pending(
                request.session_id, request.customer_id
            )
            self.store.record_trace(
                request.session_id,
                "move_cancelled" if cancelled else "cancellation_rejected",
                {
                    "request_id": request.request_id,
                    "outcome": "cancelled" if cancelled else "no_awaiting_proposal",
                },
            )
            if cancelled:
                return AgentReply(message="The pending move request was cancelled.")
            return AgentReply(message="There is no pending move request to cancel.")

        self.store.record_trace(
            request.session_id,
            "response_returned",
            {"request_id": request.request_id, "outcome": "informational"},
        )
        return AgentReply(message=decision.reply)
