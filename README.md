# Clankers relay — safely handling bug reports from outsiders

Flip the Switch hackathon (WeMakeDevs), Track 01 Best Business Workflow.
Team: md (`@mddragon18_`), Max, Nithin, Pranav. Submission is made by a human; the bots
here are not team members.

## TL;DR

- An untrusted bug report from outside the team arrives as plain Mattermost text and gets
  **no Switch credential at all**.
- A deterministic relay (plain Python, no model on the message path) validates it against a
  fixed contract and forwards **exactly** `{"file", "severity", "summary"}` into the
  engineering room.
- The trusted engineer agent works only from that validated ticket, fixes the bug on a
  throwaway branch, opens a PR, and a **human merges**.
- The demo target is a real bug in a repo the judges know: `NousResearch/hermes-agent#148719`
  item 3 — the machine uv cache PM creates and nothing reaps. Our fix merged on our fork:
  [mddragon18/hermes-agent#2](https://github.com/mddragon18/hermes-agent/pull/2).

## What Switch does, and what the relay does

Switch records the room and the human approval. The relay enforces what crosses. We measured
where Switch's own room isolation fell short (known roster gap #805 on 0.31.0).

Direct cross-room reads, posts and history **are** enforced by Switch: an agent that is not a
room member gets `403 Agent is not a member of this room` on both the `ops/*` and `moderation/*`
surfaces, measured with the untrusted agent's own credential (`evidence/demo-run.log`, step 6).
The HTTP 500 we hit on authorization refusals exists only on the pinned `0.31.0` image's legacy
moderation route; on `main` that route is gone and the 4xx refusal is covered by
`core/tests/switch_core/bridges/agent/api/test_refusal_status_codes.py`. Nothing here was filed
as a vulnerability: the gap is already tracked publicly as #805 with fixes open.

## The contract

```json
{"file": "...", "severity": "...", "summary": "..."}
```

Nothing else crosses, on purpose. There is **no free-text `evidence` field**: an evidence string
is another channel for outsider text straight into the trusted agent's context, and this target's
repro is a fixed one-liner (`du -sh ~/.hermes/cache/uv`), so free text buys nothing.

The relay rejects:

- any key other than `file`, `severity`, `summary`
- a `file` that does not resolve inside the engineering repo (traversal, absolute paths,
  escaping the repo root, symlink escape)
- instruction-shaped `summary` text ("ignore previous instructions", shell pipelines, URLs)
- severity outside `blocker|critical|high|medium|low`
- `summary` over the length cap, and non-printable characters

It renders the accepted payload as quoted JSON, never as a prompt.

## Roles on the live stack

| identity | owner | rooms |
|---|---|---|
| `support-inbox` | registration token (Agent Bootstrap) | its own room only |
| `clankers-relay` | minted owner API key | both rooms, own memberships, `scope=all` `filter=all` |
| `release-engineer` | minted owner API key | engineering room only |

One relay connection, member of both rooms, filtering every message it reads. It never borrows
another agent's credential or placement. The inbox side holds no Switch credential precisely
because of the finding above.

## Run it

```bash
cd relay
uv run --with pytest pytest -q test_relay_contract.py   # 58 passed
python3 demo_run.py                                     # live stack, end-to-end crossing
```

`demo_run.py` tears down any previous run first, so it is clean-room reproducible. It registers
the three identities, creates both rooms, posts one well-formed ticket and one hostile payload as
the untrusted agent, and records the relay read, each verdict, what the engineer actually sees,
and the untrusted agent's refused direct read. Credentials stay in a `0600` state file and never
reach the log.

## Evidence (`evidence/`)

| file | what it proves |
|---|---|
| `demo-run.log` | the full crossing: ticket accepted, injection rejected, engineer sees only the ticket, untrusted direct read `403` |
| `relay-contract-tests.log` | `58 passed` |
| `recheck-2026-11-05.log` | the corrected measurement behind the claim wording |
| `hermes-fix-red.log` | the regression test failing **before** the fix |
| `hermes-fix-green-targeted.log` | `22 passed` **after** the fix |
| `cache-prune-livecheck.log` | the fix run against a sample copied out of the real cache |

The demo run's exact lines:

```
step 3 — ACCEPTED file=pm/packages.py severity=high
         REJECTED (unknown field(s) in contract: evidence)
step 4 — forwarded: {"file": "pm/packages.py", "severity": "high", "summary": "..."}
step 5 — engineering room shows the validated ticket: True
         engineering room shows the hostile text: False
step 6 — direct cross-room read by support-inbox: 403 {"detail":"Agent is not a member of this room"}
RESULT: DEMO OK
```

## The fix, fail-before / pass-after

```
E   ModuleNotFoundError: No module named 'pm.cache_maintenance'   # before
22 passed in 13.58s                                                # after
```

Measured on this box: `du -sh ~/.hermes/cache/uv` → `1.8G`, 355 archive buckets, 467 wheel/sdist
index entries, 187 of them dists the repo's `uv.lock` cannot resolve. `hermes pm cache-prune`
against a 53 MB sample copied out of that real cache: `removed 60 superseded entries, reclaimed
21.6 MB`, with the 12 in-lock entries intact.

## Honest residual risk

- The relay guarantees **shape**, not meaning. Worst case it forwards a technically well-formed
  ticket that is simply a lie, and the engineer burns a branch on it.
- Path validation is checked against the engineering repo at relay time; if the repo moves or
  the ticket names a file that later disappears, the ticket goes stale silently.
- The relay is one process with two room memberships. Compromise of the relay host is out of
  scope; the trust boundary we enforce is between the outsider and the trusted agent's context.
- `summary` length and charset checks are deny-by-shape, not semantic analysis.
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
relay/test_relay_contract.py    58 contract tests
relay/demo_run.py               live-stack end-to-end run
findings.md                     what we measured on Switch 0.31.0, and how the framing changed
evidence/                       logs, redacted by construction (credentials never enter logs)
VIDEO-SCRIPT.md                 3-minute walkthrough, claim-by-claim against the logs
```
