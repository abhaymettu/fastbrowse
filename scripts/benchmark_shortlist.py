"""Compare one distribution with repeated choices under a fixed, offline model delay."""

import argparse
import asyncio
import json
import socket
from collections.abc import Mapping
from statistics import median
from time import perf_counter
from unittest.mock import patch

from pydantic import JsonValue

from fastbrowse.clients.validation import wire_questions
from fastbrowse.jev import ChoiceAnswer, ChoiceQuestion, Evaluation, Question
from fastbrowse.models import CostBasis, CostComponent, CostLine, Limits
from fastbrowse.shortlist import NONE, Candidate, ShortlistRequest, shortlist
from fastbrowse.telemetry import Ledger

UPSTREAM_SHA = "1231850a0bf1a0c0341fe408ef1668dbbfdfac46"


class DelayedFixtureJev:
    def __init__(self, weights: Mapping[str, int], delay_ms: float) -> None:
        self.weights = weights
        self.delay_ms = delay_ms
        self.calls = 0
        self.request_bytes = 0

    async def evaluate(self, state: JsonValue, questions: Mapping[str, Question]) -> Evaluation:
        self.calls += 1
        self.request_bytes += len(json.dumps({"state": state, "questions": wire_questions(questions)}).encode())
        question = questions["shortlist"]
        assert isinstance(question, ChoiceQuestion)
        weights = {key: self.weights.get(key, 0) for key in question.criteria}
        total = sum(weights.values())
        await asyncio.sleep(self.delay_ms / 1000)
        return Evaluation(
            model="offline-fixed-delay",
            answers={
                "shortlist": ChoiceAnswer(
                    choice=max(weights, key=lambda key: weights[key]),
                    probabilities={key: weight / total for key, weight in weights.items()},
                    confidence=0.95,
                )
            },
            input_tokens=0,
            cost=CostLine(component=CostComponent.JEV, basis=CostBasis.ESTIMATED, dollars=0),
        )


async def measure(count: int, *, repeats: int, delay_ms: float) -> dict[str, object]:
    candidates = tuple(Candidate(id=f"c{i}", description=f"Observed candidate {i}") for i in range(count))
    request = ShortlistRequest(task="Rank relevant observed candidates", state_key="fixture-v1", candidates=candidates)
    weights = {candidate.id: count - index for index, candidate in enumerate(candidates)}
    assert NONE not in weights
    expected = [candidate.id for candidate in candidates[:3]]
    timings: dict[str, list[float]] = {"distribution": [], "serial": []}
    measurements: dict[str, object] = {}
    for mode in timings:
        for _ in range(repeats):
            jev = DelayedFixtureJev(weights, delay_ms)
            ledger = Ledger(Limits())
            started = perf_counter()
            if mode == "distribution":
                result = await shortlist(jev, request, ledger=ledger)
                chosen = [suggestion.id for suggestion in result.suggestions]
            else:
                chosen: list[str] = []
                for _ in range(3):
                    remaining = tuple(candidate for candidate in candidates if candidate.id not in chosen)
                    result = await shortlist(
                        jev, request.model_copy(update={"candidates": remaining, "limit": 1}), ledger=ledger
                    )
                    chosen.extend(suggestion.id for suggestion in result.suggestions)
            timings[mode].append((perf_counter() - started) * 1000)
            assert chosen == expected
            assert ledger.jev_calls == jev.calls == (1 if mode == "distribution" else 3)
        measurements[mode] = {
            "evaluate_calls_per_shortlist": jev.calls,
            "request_bytes_per_shortlist": jev.request_bytes,
            "fixture_wait_ms_per_shortlist": jev.calls * delay_ms,
            "elapsed_ms_median": round(median(timings[mode]), 3),
            "elapsed_ms_min": round(min(timings[mode]), 3),
            "elapsed_ms_max": round(max(timings[mode]), 3),
        }
    return {"candidate_count": count, "expected_and_returned": expected, **measurements}


async def benchmark(*, repeats: int = 7, delay_ms: float = 20) -> dict[str, object]:
    if repeats < 1 or delay_ms < 0:
        raise ValueError("repeats must be positive and delay nonnegative")

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("the shortlist benchmark cannot use the network")

    with patch.object(socket.socket, "connect", forbidden), patch.object(socket, "getaddrinfo", forbidden):
        cases = [await measure(count, repeats=repeats, delay_ms=delay_ms) for count in (3, 16, 32)]
    return {
        "schema_version": 1,
        "upstream_sha": UPSTREAM_SHA,
        "method": "One distribution versus three successive top-one choices on the same fixed ranking.",
        "latency_source": "Offline fixture sleep; not a live provider or end-to-end browsing measurement.",
        "repeats_per_mode": repeats,
        "fixture_delay_ms_per_evaluate": delay_ms,
        "network_calls": 0,
        "credentials_used": 0,
        "effects_dispatched": 0,
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--delay-ms", type=float, default=20)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(benchmark(repeats=args.repeats, delay_ms=args.delay_ms)), indent=2))


if __name__ == "__main__":
    main()
