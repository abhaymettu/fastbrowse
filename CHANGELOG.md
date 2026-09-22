# Changelog

What changed in each release, in the terms someone using fastbrowse would notice. Dates are UTC.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). The entries are prose rather than bare
Added/Fixed lists: what matters about a browser agent's release is why a behaviour changed.

The version on PyPI is what these entries describe: `uvx fastbrowse@0.3.3` runs exactly the release below it.
Older entries are kept verbatim rather than rewritten as the product moves.

## [Unreleased]

- **`fastbrowse-judge` asks Jev one question from the shell.** `choose` picks one of the options you name and
  `score` places the input on levels you order; the input comes from `--text` or stdin. It prints one JSON
  object and exits 0 when Jev decided, 3 when it was unsure, 4 when it could not be asked (no key, a timeout, a
  failed request or an answer that failed validation), and 2 for a bad command line. The answer is advice: the
  judge runs nothing and grants nothing, so a script that acts on it is making its own call.

## [0.4.2] - 2026-09-20

- **A form is set up in the order that works.** Its mode - which tab of a search, which kind of account or
  ticket, which category - decides which fields it has and empties what they hold, so it is chosen before
  any value is typed rather than after, which used to mean typing the values twice. The filters a task asks
  for are set before submitting where the form offers them, because setting one afterwards submits twice,
  and a filter the page only reveals once there are results is set there. On a flight search this removed
  five steps of rework; on a two-package comparison it removed the repeated writes to the search box that
  had made it the most expensive lookup in the suite.

## [0.4.1] - 2026-09-20

- **A secret can be declared for a site rather than for one of its hosts.** `https://*.example.com` covers
  `www.example.com`, `accounts.example.com` and `example.com` itself, which is how one sign-in spans a site:
  the login typed on the account host is the login the shop host asks for. The wildcard
  stands for whole labels only, so it does not cover `example.com.evil.test`, and neither the scheme nor the
  port is ever wildcarded. An exact origin behaves exactly as before. This reaches the MCP server too
  (`--secret NAME=ENV_VAR@https://*.example.com`), where each secret keeps the scope it was declared with
  rather than the start page's.
- **`ScopedSecrets.per_secret({name: (value, origins)})`** holds a person's credentials each scoped to the
  sites it belongs to, for an application that stores them that way. The single-origin constructor is
  unchanged.
- **An IPv6 origin survives being read back.** `origin_of` returned `https://::1`, which is not a URL any
  parser reads again, so a check against an IPv6 origin could raise rather than answer. The literal keeps its
  brackets.

## [0.4.0] - 2026-09-20

Everything an application needs to run fastbrowse as its browser engine rather than as a command someone
types. Each of these came from wiring it into a product that already had one.

- **Drive a browser you already have.** `cdp_url` attaches to any browser over the DevTools protocol,
  wherever it runs: a container, a VM, a machine you own. The run opens one tab and closes that tab, so a
  browser handed over is left exactly as it was found, and nothing is billed to a cloud account. This is the
  option to reach for when the browser should live next to the user rather than in someone else's cloud.
- **Start from the task alone.** `start` is optional now. A caller whose own interface takes a goal and no
  URL had nowhere to get one; the first address is worked out from the task, as a person would. `--start`
  is optional in the CLI and `start` is optional on the MCP server's `browse` tool, where `task` is now the
  only thing a call must carry, and it holds for an attached browser too, which the run opens its own tab on.
  A secret is only ever typed on the start origin, so asking for one without a start page is refused rather
  than quietly dropped.
- **Stop a cloud browser you did not start.** The browser event carries the cloud browser's id, so an
  application that has to end a run out of band (a user pressing cancel, a subscription ending) can.
- **`proxy_country` and `viewport`** reach a cloud browser the run starts, instead of being fixed at what
  the library guessed.

Fixed in the same release, from tasks that failed in the field:

- **A list longer than one page is answered from the whole of it.** A task over a paginated catalogue read the
  first page, answered from it and called that done. The run now follows the pager until what was asked for is
  evidenced or the page cap is reached, the reader is told when the page it is reading continues, and a claim
  about a whole list is not accepted from one page of it.
- **A bot check is reported as one.** `Status.BLOCKED` is new: a CAPTCHA is not a sign-in and no credential
  passes it, so a run that meets one says so rather than ending as `stuck`. A challenge that clears itself once
  its script runs is still waited out first, and the check is made whether or not a secret is held for the site.
- **A reply cut short is asked for again.** A read whose answer hit the output limit was parsed as though it
  were whole, so facts after the cut were lost without a word.
- **`--json` keeps its contract on a bad limit.** `--max-steps 0` printed a traceback and nothing parseable; it
  is now refused like any other bad flag, with the error on stdout as JSON.
- **A limit reads as what it is** in the message that reports it: a dollar limit as money, a duration as a
  duration.

## [0.3.4] - 2026-09-20

- **A step frame can no longer carry a secret the step itself revealed.** `Config(step_frames=True)` checked
  whether a resolved secret was on screen using the reading of the page the step was decided from, which is
  the page *before* the action ran. A fill that a page mirrors into ordinary text put the secret on the page
  after that check, so the frame sent to the caller could contain it as pixels. The check now reads the page
  as it is when the image is taken. Affects 0.3.2 and 0.3.3 with step frames enabled; no other surface sent
  an image.

## [0.3.3] - 2026-09-20

- **Runs on Python 3.13.** The floor was 3.14, which an application pinned below that could not work around:
  `uv add fastbrowse` simply would not resolve. Nothing in the package needed 3.14. CI now runs the whole gate
  on 3.13 and 3.14, so the floor is exercised rather than claimed.

## [0.3.2] - 2026-09-20

- **A picture of each step, for an interface that shows a run as it happens.** `Config(step_frames=True)` puts
  a PNG of the page a step acted on onto every step event. It is off by default, because it costs a screenshot
  round trip per step. A step whose page is showing a resolved secret sends no frame: pixels cannot be masked
  the way text is.

## [0.3.1] - 2026-09-20

- **A cloud browser can run as a profile someone already signed in.** `--cloud-profile ID`,
  `run_task(cloud_profile=...)` and the MCP server's `--cloud-profile` start a Browser Use Cloud browser from
  one of that account's profiles, so a run acts as whoever set the profile up. No credential is shown to a
  model, and a local run's `--profile DIR` keeps working as before. Passing a cloud profile id to local Chrome
  is refused rather than ignored.
- **Install from PyPI.** The README opened with `git clone`, which was the only way to run fastbrowse before it
  was published and is now the contributor path. It opens with `uvx fastbrowse`.

## [0.3.0] - 2026-09-20

- **A list split across pages is read whole.** Counting or ranking over a paginated list had no path to the
  answer: a run either stopped at the step limit or finished early on page one. The reader can now say a list
  continues past the page it read, a claim from part of a list cannot close the question, and when a page has a
  single next-page link the agent follows it and reads what it opened without asking the choice model each time.
- **A click that changed nothing is not repeated.** An action that left the page as it was goes to recovery
  instead of being taken again from the same page, and fields a form will not submit without (required and
  empty, or marked invalid) are named in what the action reports.
- **An MCP server.** `fastbrowse-mcp` serves one `browse` tool over MCP, so Claude Code, Claude Desktop, Cursor
  or any other client can hand it a task. What a calling model may do is fixed by the operator's flags: a call
  can ask for less, never more.
- **Runs on Windows.** A checkout failed before any test ran: files were read in the locale's code page, a date
  used a flag only glibc has, and Chrome was never found where its Windows installer puts it.
- Fixes found by the live suite: a run outlasts a brief provider outage, a redrawn control's twin is acted on
  rather than decided again, an empty page is drawn before it is read, a start page that never loads is tried
  again, and a finish stands when the verifier doubts only what the notes already cite.

## [0.2.0] - 2026-09-18

- **`--record FILE`** saves an MP4 of the tab, ending on the answer, its time and its cost.
- **Sign in with a stored login the task never mentions.** `--secret NAME=ENV_VAR` and `--bitwarden ITEM` type a
  credential on the start origin without the value entering a model's context.

## [0.1.0] - 2026-09-18

- First release: a browser agent that picks its next action from the controls the page actually has, with an
  LLM to plan and read, and code owning verification, safety and secrets.

[unreleased]: https://github.com/agent-labs-dev/fastbrowse/compare/v0.4.2...HEAD
[0.4.2]: https://github.com/agent-labs-dev/fastbrowse/releases/tag/v0.4.2
[0.4.1]: https://github.com/agent-labs-dev/fastbrowse/releases/tag/v0.4.1
[0.4.0]: https://github.com/agent-labs-dev/fastbrowse/releases/tag/v0.4.0
[0.3.4]: https://github.com/agent-labs-dev/fastbrowse/releases/tag/v0.3.4
[0.3.3]: https://github.com/agent-labs-dev/fastbrowse/releases/tag/v0.3.3
[0.3.2]: https://github.com/agent-labs-dev/fastbrowse/releases/tag/v0.3.2
[0.3.1]: https://github.com/agent-labs-dev/fastbrowse/releases/tag/v0.3.1
[0.3.0]: https://github.com/agent-labs-dev/fastbrowse/releases/tag/v0.3.0
[0.2.0]: https://github.com/agent-labs-dev/fastbrowse/releases/tag/v0.2.0
[0.1.0]: https://github.com/agent-labs-dev/fastbrowse/releases/tag/v0.1.0
