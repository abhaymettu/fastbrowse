# Design

fastbrowse splits a browser agent into three owners:

- **Jev picks.** Each step, one batched Jev request chooses the operation and a target for each operation from indexed page candidates, and asks whether the page needs a sign-in. Separate Jev calls ask whether a target code has flagged may be irreversible, whether the task is complete, and whether each answer claim is supported by its quote.
- **An LLM reads and writes.** Proposing a direct address for the task while the start page loads, planning checkable requirements from the task alone, reading page content for answers when Jev cannot pick a short fact from quoted spans, writing non-secret field text, recovering when Jev is unsure, verifying completion in the uncertain band, composing the final answer.
- **Code owns the gates.** Freshness and hit-tests before every input, no automatic retry of a mutation, authorization for irreversible actions, secret resolution and redaction, budgets, and the definition of success: only `COMPLETE`, which requires every requirement evidenced.

The opt-in [Jev shortlist adapter](shortlist.md) exposes bounded candidate advice to embedding callers.
It does not dispatch actions or change the default loop, and every caller gate still applies.

## Browser capabilities over plain CDP (P0 spike, 2026-09-17)

Verified with `cdp-use==1.4.5` against local headless Chrome and a Browser Use cloud browser:

| Capability | Mechanism | Local | Cloud |
|---|---|---|---|
| Own tab rendered | `Target.createTarget(background=not remote)` + `activateTarget` | pass | pass |
| Upload caller bytes | in-page `DataTransfer` + `File` on the input, `input`/`change` events (no host path needed) | pass | pass |
| Download bytes | `Fetch.enable` at Response stage for Document responses (download-attribute anchors included), `Fetch.getResponseBody` on `Content-Disposition: attachment` | pass | pass |
| Cross-origin iframe | `Target.setAutoAttach(flatten)` on the page session, evaluate in the iframe session | pass | pass |
| Popup ownership | `Target.targetCreated.openerId` equals our target | pass | pass |
| Dialogs | `Page.javascriptDialogOpening` + `Page.handleJavaScriptDialog` | pass | pass |

The cloud browser ignores `Browser.setDownloadBehavior(deny)`, so bytes come from response interception, never from the remote filesystem. Host-path `DOM.setFileInputFiles` is only valid for a browser on the same machine.
