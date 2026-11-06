# Clankers relay — safely handling bug reports from outsiders

Flip the Switch hackathon (WeMakeDevs), Track 01 Best Business Workflow.
Team: md (`@mddragon18_`), Max, Nithin, Pranav. Submission is made by a human; the bots
here are not team members.

## TL;DR

- An outsider reports a bug in plain Mattermost text. That account has **no Switch agent record,
  no Switch API key, and no room membership** — the wired run reads the Switch agent roster and
  shows the outsider absent, then shows the Switch API refusing that chat token (`401`)
  (`evidence/demo-run-mattermost.log`, step 2).
- An ingest bridge moves the raw text from the public channel into the Switch inbox room as the
  inbox agent's connector. It enforces nothing: it is transport, so enforcement lives in one place.
- A deterministic relay (plain Python, no model on the message path) validates against a fixed
  contract and forwards **exactly** `{"file", "severity", "summary"}` into the engineering room.
- The trusted engineer agent works only from that validated ticket, fixes the bug on a throwaway
  branch, opens a PR, and a **human merges**.
- Demo target: a real bug in a repo the judges know — `NousResearch/hermes-agent#148719` item 3,
  the uv cache Hermes creates and nothing reaps. Our fix merged on our fork:
  [mddragon18/hermes-agent#2](https://github.com/mddragon18/hermes-agent/pull/2).
- Scope against open upstream work: [#128030](https://github.com/NousResearch/hermes-agent/pull/128030)
  normalizes the *comparison* side of the same pruner (spelling like `ruamel.yaml` vs lock name
  `ruamel-yaml`); our patch fixes the *parse* side (`dist_info` captured `[^-]+`, so hyphenated dist
  names never matched and their buckets were kept forever). Different halves, both needed, and ours
  composes with theirs. [#139381](https://github.com/NousResearch/hermes-agent/pull/139381) touches the
  cache-seed merge, not pruning. The doctor warning-text half of item 3 belongs to
  [#128474](https://github.com/NousResearch/hermes-agent/issues/128474) and is not ours.

## What Switch does, and what the relay does

Switch records the room and the human approval. The relay enforces what crosses. We measured
where Switch's own room isolation fell short (known roster gap #805 on 0.31.0).

Direct cross-room reads, posts and history **are** enforced by Switch: an agent that is not a
room member gets `403 Agent is not a member of this room` on both the `ops/*` and `moderation/*`
surfaces, measured with the untrusted agent's own credential (`evidence/demo-run.log` step 6,
`evidence/demo-run-mattermost.log` step 8). The HTTP 500 we hit on authorization refusals exists
only on the pinned `0.31.0` image's legacy moderation route; on `main` that route is gone and the
4xx refusal is covered by `core/tests/switch_core/bridges/agent/api/test_refusal_status_codes.py`.
Nothing here was filed as a vulnerability: the gap is already tracked publicly as #805 with fixes
open.

## The path, end to end

```
outsider (Mattermost account only)
   │  posts "FINDING {...}" into the public channel outsider-reports
   ▼
mattermost_feed.py   ingest bridge — Mattermost token + support-inbox agent key, no enforcement
   │  hands the raw payloads over verbatim into support-inbox-room
   ▼
relay.py             the only crossing point: validates, forwards accepted tickets only
   │  RELAY {"file","severity","summary"}
   ▼
engineering-room     release-engineer works from the ticket alone
   ▼
throwaway branch → PR → human merges
```

Two runnable variants, both live-tested on a real stack:

- `demo_run.py` — Switch-native: the untrusted inbox agent posts the payloads itself.
- `demo_run_mattermost.py` — the real front door: outsider text enters through Mattermost, the
  bridge carries it, and the outsider's chat token is refused by the Switch API (`401`).

## The contract

```json
{"file": "...", "severity": "...", "summary": "..."}
```

Nothing else crosses, on purpose. There is **no free-text `evidence` field**: an evidence string
is another channel for outsider text straight into the trusted agent's context, and this target's
repro is a fixed one-liner (`du -sh ~/.hermes/cache/uv`), so free text buys nothing.

The relay rejects:

- any key other than `file`, `severity`, `summary`, and any payload missing a field
- a payload that is not a JSON object, or fields that are not strings
- a `file` that is not an ordinary repo-relative path (absolute, drive-letter, backslash, parent
  traversal), that resolves outside the repo after `realpath` (a symlink hop out of the checkout is
  refused by the same rule), or that does not exist as a regular file in the engineering checkout
- severity outside `low|medium|high|critical`
- `summary` that is empty, whitespace-only, or longer than 400 characters
- `summary` carrying instruction markers (`ignore previous`, `system prompt`, `your instructions`,
  `run `, `curl `, `wget `, `rm -`, `sudo `, `git push`, …) or shell syntax (`$(`, backtick,
  `; rm`, `&&`, `||`)

Accepted payloads are rendered as quoted JSON, never as a prompt. The rejection reason goes back
to the inbox — it names the offending field and nothing else.

## Roles on the live stack

| identity | owner | rooms |
|---|---|---|
| `support-inbox` | registration token (Agent Bootstrap) | its own room only |
| `clankers-relay` | minted owner API key | both rooms, own memberships, `scope=all` `filter=all` |
| `release-engineer` | minted owner API key | engineering room only |

The relay holds one Switch connection, is a member of both rooms, and filters every message it
reads. It never borrows another agent's credential or placement. The outsider side holds no
Switch credential at all: it is a Mattermost account, and the wired run shows the Switch API
refusing that account's chat token (`401 Invalid credentials`).

## Run it

```bash
cd relay
uv run --with pytest pytest -q test_relay_contract.py test_mattermost_feed.py   # 78 passed
python3 demo_run.py                                                              # Switch-native variant
python3 demo_run_mattermost.py                                                   # Mattermost front door
```

Both variants tear down any previous Switch run first, so they are clean-room reproducible.
`demo_run_mattermost.py` creates or reuses the Mattermost channel and accounts, posts two findings
as the outsider, checks that chat token against the Switch API, runs the bridge, then the relay,
and records what the engineer actually sees plus both refusals. Credentials go to a `0600` state
file and never reach the logs. Env overrides (`SWITCH_BASE`, `MATTERMOST_BASE`, `ENGINEERING_REPO`,
`DOCKER_HOST`, …) are documented in `SETUP.md`.

## Evidence (`evidence/`)

| file | what it proves |
|---|---|
| `demo-run-mattermost.log` | the wired path: outsider posts `201`, chat token `401`, bridge reads 2 payloads, one ticket ACCEPTED, injection REJECTED, engineer sees only the ticket, `403` on the untrusted direct read |
| `demo-run.log` | Switch-native variant: same verdicts without the chat layer |
| `relay-contract-tests.log` | `78 passed` (59 contract + 19 feed) |
| `mattermost-feed-tests.log` | feed parsing on its own |
| `recheck-2026-11-05.log` | the corrected measurement behind the claim wording |
| `hermes-fix-red.log` | the regression test failing **before** the fix |
| `hermes-fix-green-targeted.log` | `22 passed` **after** the fix |
| `broad-suite-clean.log` | the clean broad suite around the fix: failures in 5 files, none in files this PR touches |
| `pm-base-failure.log` | the pm suite run on the **base commit, with our change absent**: `1 failed, 17 passed`, and the failure is `test_cold_runtime_e2e.py[python3.11]` — the same failure the broad run reports |
| `cache-prune-livecheck.log` | the fix run against a sample copied out of the real cache |

That pm failure is not ours: it reproduces on the base commit before any file this PR touches is
present, so it predates the change. It is a cold-runtime end-to-end test that builds its own runtime
from a served tarball, and it is the one broad-suite failure inside the package-management tree. Our
targeted runs — the cache-maintenance tests and the relay contract — are green on the fix.

Verbatim excerpt of `evidence/demo-run-mattermost.log` (the run's setup lines, which carry
internal ids, are omitted):

```
step 1 — the outsider posts both findings into the public channel (chat account only)
  posted well-formed=201 hostile=201

step 2 — the outsider's chat token is not a Switch credential
  Switch agent roster: support-inbox, release-engineer, clankers-relay
  outsider-reporter registered as a Switch agent: False
  Switch API with the Mattermost token: 401 Invalid credentials

step 3 — the ingest bridge reads the channel and hands raw payloads to Switch
  bridge read 2 finding payload(s) from the channel after 1 poll(s)
  bridge forwarded raw payload into inbox room: 200
  bridge forwarded raw payload into inbox room: 200

step 4 — the relay reads the inbox room with its OWN credential
  relay read: 200 after 1 poll(s), 2 payload(s)

step 5 — the contract relay validates each payload against the engineering repo
  ACCEPTED file=pm/packages.py severity=high
  REJECTED (unknown field(s) in contract: evidence)

step 6 — the relay forwards only validated `{file, severity, summary}`
  forwarded into engineering room: 200 {"file": "pm/packages.py", "severity": "high", "summary": "cache/uv grows forever: uv_cache_dir() creates it and no pruner reaps it, so hermes doctor warns about a directory Hermes owns"}

step 7 — the trusted engineer reads its room
  engineer read: 200 after 1 poll(s)
  engineering room shows the validated ticket: True
  engineering room shows the hostile text: False

step 8 — Switch refuses the untrusted agent's direct read of the engineering room
  support-inbox direct read: 403 {"detail":"Agent is not a member of this room"}

RESULT: DEMO OK — the outsider's report entered through Mattermost with no Switch credential; the bridge carried it as data; the relay validated one ticket and refused the injection; Switch refused every direct cross-room read
```


The run is repeat-safe: it reuses the channel and the two chat accounts, and it reads only the posts
it created this run (a cursor taken from those posts' own server timestamps), so old findings from
an earlier run can't leak into a later one. Two back-to-back runs both ended `DEMO OK`.

## The fix, fail-before / pass-after

```
E   ModuleNotFoundError: No module named 'pm.cache_maintenance'   # before
22 passed in 13.58s                                               # after
```

Measured on this box: `du -sh ~/.hermes/cache/uv` → `1.8G`, 355 archive buckets, 467 wheel/sdist
index entries, 187 of them dists the repo's `uv.lock` cannot resolve. `hermes pm cache-prune`
against a 53 MB sample copied out of that real cache: `removed 60 superseded entries, reclaimed
21.6 MB`, with the 12 in-lock entries intact.

## Honest residual risk

- The relay guarantees **shape**, not meaning. Worst case it forwards a well-formed ticket that is
  simply a lie, and the engineer burns a branch on it.
- Path validation is checked against the engineering repo at relay time; if the repo moves or the
  ticket names a file that later disappears, the ticket goes stale silently.
- The relay is one process with two room memberships. Compromise of the relay host is out of
  scope; the boundary we enforce is between the outsider and the trusted agent's context.
- Instruction filtering is deny-by-shape, not semantic analysis. A patient attacker can write a
  summary that reads like a description — it still cannot add fields, paths, or severity.
- The Mattermost front door here uses a channel every workspace member can post to, and the
  outsider account is created by the demo script. In a production deployment the outsider is a
  real workspace guest; the credential boundary is identical.
- Everything measured is scoped to Switch `0.31.0` in this configuration. We do not claim it
  holds for other versions or deployments.

## Prior art

- Willison, *LLMs can't be trusted to summarise or translate text you didn't provide, a security
  concern for RAG and chat bots* (2023) — the dual-LLM split this design follows.
- CaMeL, *Defeating Prompt Injections by Design*, arXiv:2503.18813 — capabilities, not model
  trust, on the control path.
- *Design Patterns for Securing LLM Agents against Prompt Injections*, arXiv:2506.08837 —
  the sandboxed-agent / data-flow-boundary pattern.
- Switch issue #805 (room roster gap) and #1045 (refusal status codes) — the upstream context
  for what Switch does and does not enforce on `0.31.0`.

## Layout

```
relay/relay.py                  deterministic validator
relay/mattermost_feed.py        Mattermost ingest bridge — the front door
relay/test_relay_contract.py    59 contract tests
relay/test_mattermost_feed.py   19 feed tests, offline (transport monkeypatched)
relay/demo_run.py               live-stack run, Switch-native variant
relay/demo_run_mattermost.py    live-stack run through the Mattermost front door
findings.md                     what we measured on Switch 0.31.0, and how the framing changed
evidence/                       logs, redacted by construction (credentials never enter logs)
README.md                       this file
SUBMISSION.md                   the text for the WeMakeDevs submission form
VIDEO-SCRIPT.md                 3-minute walkthrough, claim-by-claim against the logs
SETUP.md                        identities, rooms, env vars, endpoints, honest limits
```
