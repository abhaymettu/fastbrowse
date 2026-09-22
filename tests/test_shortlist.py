"""Offline advice fixtures run before any caller may dispatch an effect."""

import asyncio
import json
import socket
from collections.abc import Mapping
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import JsonValue, ValidationError

from fastbrowse.jev import ChoiceAnswer, Evaluation, JevError, NoulAnswer, Question
from fastbrowse.models import CostBasis, CostComponent, CostLine, Limits, Operation, Status, StepOutcome
from fastbrowse.page import ActResult, Control, Page
from fastbrowse.shortlist import Candidate, ShortlistRequest, shortlist
from fastbrowse.telemetry import BudgetExceeded, Ledger
from scripts.benchmark_shortlist import benchmark
from tests.test_agent import Agent, _Stop, run_state
from tests.test_policy import ScriptedJev, observation
from tests.test_retrieval import ScriptedLLM

CASES = json.loads((Path(__file__).parent / "fixtures" / "shortlist.json").read_text())
COST = CostLine(component=CostComponent.JEV, basis=CostBasis.ESTIMATED, dollars=0.00001)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("shortlist fixtures cannot use the network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def request(**changes: object) -> ShortlistRequest:
    return ShortlistRequest.model_validate(
        {
            "task": "Open the matching result",
            "state_key": "fixture-state-1",
            "candidates": [
                {"id": "open", "description": "Open the observed result"},
                {"id": "read", "description": "Read the current page"},
                {"id": "back", "description": "Return to the preceding page"},
            ],
            **changes,
        }
    )


class FixtureJev:
    def __init__(self, answer: ChoiceAnswer | NoulAnswer) -> None:
        self.answer = answer
        self.calls = 0

    async def evaluate(self, state: JsonValue, questions: Mapping[str, Question]) -> Evaluation:
        self.calls += 1
        return Evaluation(model="fixture", answers={"shortlist": self.answer}, cost=COST, input_tokens=40)


def valid_jev() -> FixtureJev:
    return FixtureJev(ChoiceAnswer(choice="open", probabilities=CASES[0]["probabilities"], confidence=0.95))


@pytest.mark.parametrize("case", CASES, ids=[case["name"] for case in CASES])
async def test_fixture(case: dict[str, object]) -> None:
    jev = FixtureJev(ChoiceAnswer.model_validate({key: case[key] for key in ("choice", "probabilities", "confidence")}))
    ledger = Ledger(Limits())
    result = await shortlist(jev, request(), ledger=ledger)
    assert result.reason == case["reason"]
    assert [item.id for item in result.suggestions] == case["expected"]
    assert result.state_key == "fixture-state-1"
    assert jev.calls == ledger.jev_calls == 1
    assert result.cost == (COST,) and ledger.lines == [COST]
    assert result.input_tokens == 40


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
async def test_nonfinite_or_boolean_probabilities_abstain(value: float) -> None:
    # A client is a protocol, so its typed output still needs boundary validation.
    answer = ChoiceAnswer.model_construct(
        choice="open", probabilities={**CASES[0]["probabilities"], "open": value}, confidence=0.95
    )
    result = await shortlist(FixtureJev(answer), request(), ledger=Ledger(Limits()))
    assert result.reason == "invalid_response" and not result.suggestions


@pytest.mark.parametrize(
    "changes",
    [
        {"candidates": [{"id": "same", "description": "A"}, {"id": "same", "description": "B"}]},
        {"candidates": [{"id": "__none__", "description": "Reserved"}]},
        {"candidates": [{"id": str(i), "description": "A"} for i in range(33)]},
        {"limit": 6},
        {"limit": 0},
        {"timeout_seconds": 1.01},
        {"timeout_seconds": 0},
        {"task": "x" * 2001},
    ],
)
def test_invalid_input_is_rejected_before_a_call(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        request(**changes)


@pytest.mark.parametrize("oversized", [False, True])
async def test_empty_or_oversized_input_never_calls_jev(oversized: bool) -> None:
    candidates = [Candidate(id=str(i), description="x" * 1000) for i in range(32)] if oversized else []
    jev = valid_jev()
    ledger = Ledger(Limits())
    result = await shortlist(jev, request(candidates=candidates), ledger=ledger)
    assert result.reason == ("too_large" if oversized else "empty")
    assert not result.suggestions and not result.cost
    assert jev.calls == ledger.jev_calls == 0


async def test_limit_and_state_binding() -> None:
    result = await shortlist(valid_jev(), request(limit=1, state_key="new-state"), ledger=Ledger(Limits()))
    assert [item.id for item in result.suggestions] == ["open"]
    assert result.state_key == "new-state"


async def test_wrong_answer_type_abstains() -> None:
    result = await shortlist(FixtureJev(NoulAnswer(probability=1)), request(), ledger=Ledger(Limits()))
    assert result.reason == "invalid_response" and not result.suggestions


class WaitingJev:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.drained = asyncio.Event()

    async def evaluate(self, state: JsonValue, questions: Mapping[str, Question]) -> Evaluation:
        self.started.set()
        try:
            await asyncio.Future[None]()
        finally:
            self.drained.set()
        raise AssertionError("unreachable")


async def test_timeout_cancels_and_drains_without_retry() -> None:
    jev = WaitingJev()
    ledger = Ledger(Limits())
    result = await shortlist(jev, request(timeout_seconds=0.001), ledger=ledger)
    assert result.reason == "timeout" and not result.suggestions
    assert jev.drained.is_set() and ledger.jev_calls == 1
    assert ledger.breakdown().has_unknown


async def test_caller_cancellation_propagates_and_drains() -> None:
    jev = WaitingJev()
    ledger = Ledger(Limits())
    task = asyncio.create_task(shortlist(jev, request(), ledger=ledger))
    await jev.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert jev.drained.is_set() and ledger.breakdown().has_unknown


async def test_provider_error_does_not_disclose_its_body() -> None:
    class BrokenJev:
        async def evaluate(self, state: JsonValue, questions: Mapping[str, Question]) -> Evaluation:
            raise JevError("provider echoed private input")

    result = await shortlist(BrokenJev(), request(), ledger=Ledger(Limits()))
    assert result.reason == "unavailable" and not result.suggestions
    assert "private input" not in result.model_dump_json()


async def test_budget_denial_precedes_model_call() -> None:
    jev = valid_jev()
    ledger = Ledger(Limits(max_jev_calls=1))
    ledger.reserve(CostComponent.JEV)
    with pytest.raises(BudgetExceeded):
        await shortlist(jev, request(), ledger=ledger)
    assert jev.calls == 0


async def test_timeout_cannot_hide_unknown_spend_from_a_dollar_cap() -> None:
    ledger = Ledger(Limits(max_dollars=1))
    with pytest.raises(BudgetExceeded, match="no cost"):
        await shortlist(WaitingJev(), request(timeout_seconds=0.001), ledger=ledger)


async def test_reported_cost_cannot_bypass_a_dollar_cap() -> None:
    with pytest.raises(BudgetExceeded, match="spend limit"):
        await shortlist(valid_jev(), request(), ledger=Ledger(Limits(max_dollars=0.000001)))


@pytest.mark.parametrize(
    ("operation", "expected"),
    [(Operation.CLICK, Status.NEEDS_CONFIRMATION), (Operation.UPLOAD, Status.NEEDS_INPUT)],
)
async def test_ranked_advice_does_not_grant_authorization_or_supply_a_capability(
    operation: Operation, expected: Status
) -> None:
    from fastbrowse.agent import _code_decision

    target = Control(id="open", role="button", label="Send message", frame_id=None, operations=frozenset({operation}))
    state = await run_state()
    advice = await shortlist(valid_jev(), request(), ledger=state.ledger)
    candidates = {target.id: target}
    chosen = candidates[advice.suggestions[0].id]
    page = Mock(spec=Page)
    agent = Agent(page, ScriptedJev({}, noul=0.99), ScriptedLLM([]))
    with pytest.raises(_Stop) as stopped:
        await agent._step(state, observation((target,)), _code_decision(operation, chosen))
    assert stopped.value.status is expected
    page.act.assert_not_called()
    assert not state.steps


async def test_ranked_advice_does_not_turn_a_noop_into_progress() -> None:
    from fastbrowse.agent import _code_decision

    target = Control(
        id="open",
        role="link",
        label="Open",
        frame_id=None,
        href="https://example.test/result",
        operations=frozenset({Operation.CLICK}),
    )
    state = await run_state()
    advice = await shortlist(valid_jev(), request(), ledger=state.ledger)
    assert advice.suggestions[0].id == target.id
    page = Mock(spec=Page)
    page.act = AsyncMock(return_value=ActResult(outcome=StepOutcome.EXECUTED, page_changed=False))
    agent = Agent(page, ScriptedJev({}), ScriptedLLM([]))
    await agent._step(state, observation((target,)), _code_decision(Operation.CLICK, target))
    assert state.unchanged == 1
    assert not state.steps[0].page_changed


async def test_advice_cannot_skip_the_callers_completion_and_delivery_check() -> None:
    state = await run_state()
    advice = await shortlist(valid_jev(), request(), ledger=state.ledger)
    assert advice.suggestions
    obs = observation(())
    page = Mock(spec=Page)
    page.observe = AsyncMock(return_value=obs)
    agent = Agent(page, ScriptedJev({}, noul=0.99), ScriptedLLM([]))
    agent._recover = AsyncMock()
    agent._conclude = AsyncMock(side_effect=AssertionError("must not deliver an unverified result"))
    until = AsyncMock(return_value=False)
    assert await agent._finish(state, obs, None, until) is None
    until.assert_awaited_once_with(obs.url)
    agent._conclude.assert_not_called()
    page.act.assert_not_called()


async def test_a_stale_target_stays_stale_after_ranking() -> None:
    from fastbrowse.agent import _code_decision

    target = Control(
        id="open",
        role="link",
        label="Open",
        frame_id=None,
        href="https://example.test/result",
        operations=frozenset({Operation.CLICK}),
    )
    state = await run_state()
    advice = await shortlist(valid_jev(), request(), ledger=state.ledger)
    assert advice.suggestions[0].id == target.id
    page = Mock(spec=Page)
    page.act = AsyncMock(return_value=ActResult(outcome=StepOutcome.STALE, page_changed=False))
    page.observe = AsyncMock(return_value=observation(()))
    agent = Agent(page, ScriptedJev({}), ScriptedLLM([]))
    await agent._step(state, observation((target,)), _code_decision(Operation.CLICK, target))
    assert state.steps[0].outcome is StepOutcome.STALE
    assert state.unchanged == 1 and page.act.await_count == 1


async def test_offline_benchmark_preserves_order_with_fewer_calls() -> None:
    receipt = await benchmark(repeats=1, delay_ms=0)
    assert receipt["network_calls"] == receipt["credentials_used"] == receipt["effects_dispatched"] == 0
    cases = receipt["cases"]
    assert isinstance(cases, list)
    assert [case["candidate_count"] for case in cases] == [3, 16, 32]
    for case in cases:
        assert case["expected_and_returned"] == ["c0", "c1", "c2"]
        assert case["distribution"]["evaluate_calls_per_shortlist"] == 1
        assert case["serial"]["evaluate_calls_per_shortlist"] == 3
