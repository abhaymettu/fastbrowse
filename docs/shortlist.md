# Bounded Jev shortlist for Jarvis

`fastbrowse.shortlist.shortlist` is an opt-in adapter for callers that need a few candidate IDs from one
Jev distribution. It accepts an existing `JevClient` and `Ledger`. It creates no client, reads no settings
or credentials, and opens no browser. The default agent loop is unchanged; this branch has no Jarvis caller
to wire in. No live eval, held-out task or provider request was used to tune this slice.

## Upstream evidence

Inspected `browser-use/jev-ultrafast` at
[`1231850a0bf1a0c0341fe408ef1668dbbfdfac46`](https://github.com/browser-use/jev-ultrafast/tree/1231850a0bf1a0c0341fe408ef1668dbbfdfac46):

- [LICENSE](https://github.com/browser-use/jev-ultrafast/blob/1231850a0bf1a0c0341fe408ef1668dbbfdfac46/LICENSE):
  MIT, copyright 2026 Browser Use.
- [pyproject.toml](https://github.com/browser-use/jev-ultrafast/blob/1231850a0bf1a0c0341fe408ef1668dbbfdfac46/pyproject.toml):
  Python >=3.12, `browser-harness==0.1.13`, `httpx[http2]>=0.28,<1`.
- [model.py](https://github.com/browser-use/jev-ultrafast/blob/1231850a0bf1a0c0341fe408ef1668dbbfdfac46/jev_ultrafast/model.py):
  TypeSafe selects operations and targets in a shared request and returns their distributions. Field text
  needs a separate OpenAI-compatible text-model endpoint and key; its default is DeepSeek.

The reusable behavior is finite-choice advice from one distribution. This adapter is a new implementation
against fastbrowse's existing Jev protocol and response validator. It copies no upstream source, imports
no upstream package, and adds no dependency. fastbrowse still requires Python >=3.13. Existing upstream
attributions in `NOTICE` remain as they were.

## Caller contract

1. Deterministic policy constructs the eligible set and binds each opaque ID to a capability in current
   state. Candidate IDs must be unique. Supply only redacted task, context and descriptions to an already
   approved client. The adapter cannot discover secrets in caller-authored text.
2. Pass a caller-owned state key, candidates and ledger to `shortlist`. The key is echoed locally and is
   not sent to Jev. No request, response body or provider exception text is logged or returned.
3. Treat returned IDs and probabilities as advice. Recheck state identity, candidate membership,
   capabilities and authorization before dispatch. The echoed key does not establish freshness. On empty
   advice, keep the existing deterministic fallback or escalate; do not execute the first input candidate.
4. Dispatch at most the action policy permits. Remaining IDs are alternatives, not a sequence to execute
   and not retries after a failed effect. Reobserve after a mutation. Existing effect checks, delivery
   checks, verification and terminalization remain authoritative.

```python
from fastbrowse.shortlist import Candidate, ShortlistRequest, shortlist

# jev and ledger belong to the caller; text has already passed its redactor.
advice = await shortlist(
    jev,
    ShortlistRequest(
        task="Find the relevant article",
        state_key=current_state_key,
        candidates=tuple(Candidate(id=key, description=label) for key, label in eligible_labels.items()),
    ),
    ledger=ledger,
)
# Feed advice to the caller's policy. No Action, RunResult or permission is produced here.
```

## Bounds and fallback

| Bound | Value |
|:--|:--|
| Candidates | 0 to 32, plus one reserved abstention option |
| Returned IDs | 1 to 5 requested, default 3; may return fewer or none |
| Task / context / description | 2,000 / 6,000 / 1,000 characters |
| Encoded state and question | At most 16,000 bytes, including instructions and JSON escaping |
| Evaluation deadline | Default 0.75 seconds, caller may set >0 through 1 second |
| Client evaluations | Zero for empty or oversized input, otherwise at most one |
| Confidence floor | 0.75, a local conservative default, not a measured accuracy guarantee |

Invalid input raises Pydantic validation before a request. Empty or oversized input returns empty advice.
Provider errors, timeout, invalid distributions, low confidence or abstention also return empty advice.
The existing response validator checks exact option membership, finite probabilities, their sum and a
maximal choice with the gateway's rounding tolerance. The chosen ID leads; other IDs sort by probability,
with input order breaking ties. Only candidates above the abstention probability survive.

The adapter does not retry. An injected transport may retry within the deadline; one `evaluate` call is
not a guarantee of one physical HTTP request. Clients must cooperate with asyncio cancellation; the
deadline cannot interrupt synchronous code or a client that suppresses cancellation. Cancellation drains
the call and propagates to the caller. A failed or cancelled call records unknown spend because it might
have been billed. A dollar cap therefore raises `BudgetExceeded` after an unpriced failure, and that
exception is never converted into advice. Normal responses record cost before returning advice.

## Fixtures and benchmark

The deterministic corpus is `tests/fixtures/shortlist.json`. The fixture suite denies socket connections
and name resolution, uses scripted clients, and covers malformed distributions, unknown IDs, abstention,
limits, cancellation, budget denial and existing caller gates. It was written and run before the adapter:
the first run failed collection because `fastbrowse.shortlist` did not yet exist.

```sh
uv run --offline pytest tests/test_shortlist.py -v
uv run --offline python scripts/benchmark_shortlist.py
```

The committed [benchmark receipt](shortlist-benchmark.json) compares a single distribution with three
successive top-one choices over the same scripted ranking at 3, 16 and 32 candidates. Each mode runs seven
times with a fixed 20 ms async delay per evaluation. Both modes return `c0`, `c1`, `c2`. The adapter uses
one call rather than three: 20 ms of fixture wait rather than 60 ms. Recorded medians are about 22 to 23 ms
versus 66 to 67 ms. Request bytes also fall because the full question need not be sent three times.

Socket access is denied during the benchmark. It uses no credentials and dispatches no effects. This is
evidence of a bounded reduction in selection calls, not a provider latency, selection quality or browsing
success claim. Real Jev probabilities may change when options are removed; the fixture ranking is fixed.
The receipt does not claim improvement over the existing agent's batched operation/target request.

No runtime endpoint, durable configuration or credential was changed. Validation installed locked
dependencies in this worktree's `.venv` and `artifacts/jev-shortlist/venv314`, using existing Python
interpreters, and synced the repository's existing Vale package. Public upstream inspection and
dependency/style downloads are the only external network work; browser tests use loopback fixtures.
Test child environments omit ambient credential variables. The shortlist fixtures make no network calls.
