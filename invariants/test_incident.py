from __future__ import annotations

import asyncio

import pytest

from invariants.conftest import build_agent


@pytest.mark.asyncio
async def test_initial_request_waits_for_approval(incident_cases, store):
    case = incident_cases[0]
    agent = build_agent(store, [case.model_decision])

    reply = await agent.handle(case.request)
    pending = store.get_pending(
        case.request.session_id,
        case.request.customer_id,
    )

    assert reply.needs_confirmation
    assert store.count_orders() == 0
    assert store.count_tool_calls() == 0
    assert pending is not None


@pytest.mark.asyncio
async def test_repeated_approval_has_one_external_effect(incident_cases, store):
    proposal, approval, replay = incident_cases
    agent = build_agent(
        store,
        [
            proposal.model_decision,
            approval.model_decision,
            replay.model_decision,
        ],
    )

    await agent.handle(proposal.request)
    first = await agent.handle(approval.request)
    second = await agent.handle(replay.request)

    assert first.completed
    assert second.completed
    assert store.count_orders() == 1
    assert store.count_tool_calls() == 1


@pytest.mark.asyncio
async def test_overlapping_approval_has_one_external_effect(incident_cases, store):
    proposal, approval, replay = incident_cases
    agent = build_agent(
        store,
        [
            proposal.model_decision,
            approval.model_decision,
            replay.model_decision,
        ],
    )

    await agent.handle(proposal.request)
    replies = await asyncio.gather(
        agent.handle(approval.request),
        agent.handle(replay.request),
    )

    assert any(reply.completed for reply in replies)
    assert store.count_tool_calls() == 1
