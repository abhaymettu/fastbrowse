import ast
import asyncio
import json
from collections.abc import Mapping
from pathlib import Path

import httpx
import pytest
from pydantic import JsonValue, ValidationError

from fastbrowse import judge
from fastbrowse.clients.typesafe import TypeSafeJevClient
from fastbrowse.clients.validation import estimated_cost
from fastbrowse.jev import Answer, ChoiceAnswer, Evaluation, JevClient, Question, ScoreAnswer

CHOOSE = ["choose", "Which area?", "--option", "browser=Page indexing", "--option", "policy=Jev questions"]
SCORE = ["score", "How risky?", "--level", "low", "--level", "medium", "--level", "high"]


class Fixed:
    """A Jev that answers with one fixed answer, and records what it was asked."""

    def __init__(self, answer: Answer) -> None:
        self.answer = answer
        self.asked: list[tuple[JsonValue, Mapping[str, Question]]] = []

    async def evaluate(self, state: JsonValue, questions: Mapping[str, Question]) -> Evaluation:
        self.asked.append((state, questions))
        return Evaluation(model="jev-test", answers={"judgment": self.answer}, input_tokens=1, cost=estimated_cost(1))


class Stalled:
    async def evaluate(self, state: JsonValue, questions: Mapping[str, Question]) -> Evaluation:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")


def run(argv: list[str], jev: JevClient | None, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict[str, JsonValue]]:
    with pytest.raises(SystemExit) as exit_:
        judge.main(argv, jev=jev)
    code = exit_.value.code
    assert isinstance(code, int)
    return code, json.loads(capsys.readouterr().out)


def typesafe(handler: httpx.MockTransport) -> tuple[TypeSafeJevClient, httpx.AsyncClient]:
    http = httpx.AsyncClient(transport=handler)
    return TypeSafeJevClient("sk-test", http=http), http


@pytest.fixture
def no_retry_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    real_sleep = asyncio.sleep

    async def immediate(_delay: float) -> None:
        await real_sleep(0)

    monkeypatch.setattr("fastbrowse.clients.validation.asyncio.sleep", immediate)


def test_a_confident_choice_is_decided_and_the_input_goes_to_jev_as_data(capsys: pytest.CaptureFixture[str]) -> None:
    jev = Fixed(ChoiceAnswer(choice="policy", probabilities={"browser": 0.1, "policy": 0.9}, confidence=0.8))
    code, out = run([*CHOOSE, "--text", "tune recover_below"], jev, capsys)
    assert code == judge.Exit.DECIDED == 0
    assert out == {
        "kind": "choice",
        "verdict": "decided",
        "choice": "policy",
        "probabilities": {"browser": 0.1, "policy": 0.9},
        "confidence": 0.8,
        "reason": None,
    }
    state, questions = jev.asked[0]
    assert state == {"input": "tune recover_below"}
    assert judge.DATA_NOTE in questions["judgment"].instructions


def test_a_low_confidence_choice_still_says_what_it_leaned_to_but_exits_uncertain(
    capsys: pytest.CaptureFixture[str],
) -> None:
    jev = Fixed(ChoiceAnswer(choice="browser", probabilities={"browser": 0.55, "policy": 0.45}, confidence=0.1))
    code, out = run([*CHOOSE, "--text", "x"], jev, capsys)
    assert code == judge.Exit.UNCERTAIN == 3
    assert out["verdict"] == "uncertain" and out["choice"] == "browser"


def test_a_score_names_its_levels_rather_than_jevs_indices(capsys: pytest.CaptureFixture[str]) -> None:
    jev = Fixed(ScoreAnswer(score=1.3, probabilities={"0": 0.1, "1": 0.5, "2": 0.4}, confidence=0.7))
    code, out = run([*SCORE, "--text", "drop a table"], jev, capsys)
    assert code == 0
    assert out["kind"] == "score" and out["level"] == "medium" and out["score"] == 1.3
    assert out["probabilities"] == {"low": 0.1, "medium": 0.5, "high": 0.4}


def test_an_answer_of_the_wrong_kind_is_unavailable_not_trusted(capsys: pytest.CaptureFixture[str]) -> None:
    jev = Fixed(ChoiceAnswer(choice="low", probabilities={"low": 1.0}, confidence=1.0))
    code, out = run([*SCORE, "--text", "x"], jev, capsys)
    assert (code, out["verdict"], out["reason"]) == (4, "unavailable", "jev_error")


async def test_a_malformed_response_is_unavailable() -> None:
    client, http = typesafe(httpx.MockTransport(lambda _: httpx.Response(200, text="{not json")))
    async with http:
        result = await judge.judge(judge.parse([*CHOOSE, "--text", "x"]), client)
    assert result == judge.ChoiceJudgment(verdict=judge.Verdict.UNAVAILABLE, reason=judge.Reason.JEV_ERROR)


@pytest.mark.usefixtures("no_retry_wait")
async def test_an_unreachable_network_is_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    client, http = typesafe(httpx.MockTransport(refuse))
    async with http:
        result = await judge.judge(judge.parse([*SCORE, "--text", "x"]), client)
    assert result == judge.ScoreJudgment(verdict=judge.Verdict.UNAVAILABLE, reason=judge.Reason.JEV_ERROR)


def test_a_stalled_jev_times_out_as_unavailable(capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run([*CHOOSE, "--text", "x", "--timeout", "0.05"], Stalled(), capsys)
    assert (code, out["reason"]) == (judge.Exit.UNAVAILABLE, "timeout")


def test_without_a_key_it_says_so_instead_of_guessing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("TYPESAFE_API_KEY", "AI_GATEWAY_API_KEY", "FASTBROWSE_JEV_SOURCE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # no .env to pick a key up from
    code, out = run([*CHOOSE, "--text", "x"], None, capsys)
    assert (code, out["verdict"], out["reason"]) == (4, "unavailable", "not_configured")


@pytest.mark.parametrize(
    "argv",
    [
        ["choose", "q", "--option", "a=A", "--text", "x"],
        ["choose", "q", "--option", "a=A", "--option", "a=B", "--text", "x"],
        ["choose", "q", "--option", "no-description", "--option", "b=B", "--text", "x"],
        ["score", "q", "--level", "only", "--text", "x"],
        [*SCORE, "--text", "   "],
        [*SCORE, "--text", "x" * (judge.MAX_INPUT_CHARS + 1)],
        [*SCORE, "--text", "x", "--timeout", "0"],
        [*SCORE, "--text", "x", "--min-confidence", "2"],
    ],
)
def test_bad_usage_exits_2_with_nothing_on_stdout(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_:
        judge.main(argv, jev=Stalled())
    assert exit_.value.code == judge.Exit.USAGE
    assert capsys.readouterr().out == ""


def test_the_output_schema_is_closed() -> None:
    with pytest.raises(ValidationError):
        judge.ChoiceJudgment.model_validate({"verdict": "decided", "authorized": True})
    with pytest.raises(ValidationError):
        judge.ScoreJudgment.model_validate({"verdict": "allow"})


def test_the_judge_cannot_execute_anything() -> None:
    # Its answer is advice; a module that could spawn a process or reach the safety gates could act on it.
    tree = ast.parse(Path(judge.__file__).read_text())
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names} | {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not imported & {"os", "subprocess", "shutil", "pty", "fastbrowse.safety", "fastbrowse.agent"}
