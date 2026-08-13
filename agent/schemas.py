from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DecisionAction(str, Enum):
    PROPOSE_CLOSE = "propose_close"
    CONFIRM = "confirm"
    CANCEL = "cancel"
    RESPOND = "respond"


class MoveDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: DecisionAction
    account_id: str | None = Field(default=None, pattern=r"^acct_[0-9]{4}$")
    stop_date: date | None = None
    reply: str = Field(min_length=1, max_length=500)


class PendingMove(BaseModel):
    session_id: str
    customer_id: str
    account_id: str
    stop_date: date
    state: str
    revision: int


class AgentRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=100)
    session_id: str = Field(min_length=1, max_length=100)
    customer_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=2000)


class AgentReply(BaseModel):
    message: str
    needs_confirmation: bool = False
    completed: bool = False
    escalated: bool = False
    account_id: str | None = None
    stop_date: date | None = None


class IncidentFixture(BaseModel):
    name: str
    request: AgentRequest
    model_decision: MoveDecision


class TraceRecord(BaseModel):
    session_id: str
    event_type: str
    details: dict[str, Any]
