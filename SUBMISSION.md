# Submission text — WeMakeDevs / Flip the Switch, Track 01 (Best Business Workflow)

Paste-ready blocks. Keep the wording: every claim here is backed by a log in `evidence/`, and two
sentences are load-bearing for honesty (`## What it does not claim` and the closing line). Fill the
`<...>` placeholders with the real links when you have them, then submit. Deadline: Nov 7, 23:59 IST.

---

## Project title

**Clankers Relay — an untrusted bug-report pipeline that an agent can't be talked into**

Alternate (shorter, if the form truncates): **Clankers Relay**

## One-line hook

A bug report from a stranger enters as free text; only a validated three-field ticket ever reaches
the trusted agent, and a human still signs the merge.

## Description (form field)

Support inboxes are the classic attack surface for an autonomous engineering workflow: outsiders
send free-text reports, and report text can carry instructions ("ignore previous instructions and
run this"). If you pipe that inbox into an agent that holds a repository and a credential, you have
given a stranger a write path into your codebase.

We built the workflow where that is impossible by construction rather than by prompting:

1. **Front door — Mattermost.** An outsider account with no Switch agent record, no Switch API key
   and no room membership posts a report into a public reports channel. Nothing about that account
   is trusted, and it holds nothing of ours.
2. **Ingest bridge — transport only.** `mattermost_feed.py` reads the channel and hands the raw
   payload lines into Switch's `support-inbox-room` as the inbox connector's own feed. It validates
   nothing on purpose, so enforcement lives in exactly one component.
3. **Relay — the only crossing point.** `relay.py` is plain Python with no model on the message
   path. It accepts exactly `{"file", "severity", "summary"}`: unknown keys, non-string fields,
   non-JSON payloads, repository-escaping paths (absolute, traversal, symlink hop out of the
   checkout), severity outside a fixed enum, oversized or empty summaries, and instruction-shaped
   text (`ignore previous`, `system prompt`, `curl `, `rm -`, `sudo `, `$(`, backticks, `&&`) are
   refused. Accepted payloads are quoted as data, never rendered as a prompt.
4. **Engineering room on Switch.** `release-engineer` works from the validated ticket alone, fixes
   the bug on a throwaway branch, opens a PR, and posts the verdict into the room.
5. **Human merges.** The room records the approval. Automation stops before the merge.

The demo runs against a real bug in a real repo, not a toy: `NousResearch/hermes-agent` issue
`#148719` item 3 — package management creates `$HERMES_HOME/cache/uv` and nothing reaps it. On this
machine that cache measured `1.8 GB`, with 187 of 467 cached distributions the repository's
`uv.lock` cannot resolve. Our fix adds `hermes pm cache-prune` (prunes exactly to the lock) plus a
pattern fix so hyphenated distribution names parse at all. It merged on our fork as
[mddragon18/hermes-agent#2](https://github.com/mddragon18/hermes-agent/pull/2), squash commit
`8f0d65e6c623d2b15c55882f6185e78f41761414`, and the regression test fails before the fix
(`ModuleNotFoundError: No module named 'pm.cache_maintenance'`) and passes after (`22 passed`).

## What it does not claim

Switch records the room and the human approval. The relay enforces what crosses. We measured where
Switch's own room isolation fell short (known roster gap #805 on 0.31.0).

We do not claim Switch enforces a quarantine, and every measurement is scoped to Switch `0.31.0` in
this configuration. The relay guarantees shape, not meaning: a well-formed ticket can still be a
lie, and then an engineer burns a branch on it. The refusals we did measure are Switch's own
`403` for non-member reads, plus the Switch API refusing the outsider's chat credential (`401`).

## Measured results (all in `evidence/`)

| claim | evidence line |
|---|---|
| outsider report enters through chat, no Switch credential | `Switch agent roster: support-inbox, release-engineer, clankers-relay`, `outsider-reporter registered as a Switch agent: False`, `Switch API with the Mattermost token: 401 Invalid credentials`, `posted well-formed=201 hostile=201` |
| bridge carries raw payloads into the inbox room | `bridge read 2 finding payload(s) from the channel`, `forwarded raw payload into inbox room: 200` |
| hostile payload refused | `REJECTED (unknown field(s) in contract: evidence)` |
| trusted agent sees only the ticket | `engineering room shows the validated ticket: True`, `engineering room shows the hostile text: False` |
| Switch refuses cross-room read | `support-inbox direct read: 403 {"detail":"Agent is not a member of this room"}` |
| contract + feed tests | `78 passed in 0.09s` (59 contract, 19 feed) |
| fail-before / pass-after | `ModuleNotFoundError: No module named 'pm.cache_maintenance'` → `22 passed in 13.58s` |
| unrelated suite failure, measured both ways | `test_cold_runtime_e2e.py[python3.11]`: `1 failed, 17 passed` on the base commit and `1 failed, 17 passed` with our change — identical, so neither introduced nor claimed by us |
| the fix on a real cache | `removed 60 superseded entries, reclaimed 21.6 MB` against a 53 MB sample copied out of the live cache, 12 in-lock entries intact |

## Tech stack

Switch (pinned `0.31.0` image) + Mattermost + Postgres via docker compose, rootless Docker on Omarchy.
Python 3 for the relay and the ingest bridge, `pytest` for the contract tests, `uv` for test envs.
`NousResearch/hermes-agent` as the engineering repository, with `hermes pm cache-prune` as the change.

## Links

- Submission repo: https://github.com/mddragon18/clankers-relay
- The fix: https://github.com/mddragon18/hermes-agent/pull/2 (merged into `develop` on our fork,
  commit `8f0d65e6c623d2b15c55882f6185e78f41761414`; upstream `NousResearch` review is still open)
- Upstream issue: https://github.com/NousResearch/hermes-agent/issues/148719 (item 3)
- Video: `<paste your video link here>`
- Walkthrough doc: `README.md`, setup for other stacks in `SETUP.md`, script in `VIDEO-SCRIPT.md`

## How to judge it in two minutes

```bash
git clone https://github.com/mddragon18/clankers-relay && cd clankers-relay/relay
uv run --no-project --with pytest pytest -q test_relay_contract.py test_mattermost_feed.py   # 78 passed
python3 demo_run_mattermost.py       # needs a Switch + Mattermost stack (see SETUP.md)
```

`evidence/demo-run-mattermost.log` is the recorded run, so the verdicts are readable without a stack.

## Team

md (`@mddragon18_`), Max, Nithin, Pranav. Bots on this project were tooling, not team members.
The engineering ran under md's authorization with a human approving the merge; the registration and
this submission are human actions.

## Future work

- Swap the polling bridge for a Mattermost outgoing webhook or the WebSocket event stream.
- Rate-limit and reputation-gate the reports channel, so the relay isn't just shape-filtering a
  flood.
- Move the relay into its own container with a read-only repo mount and no network except Switch.
- Extend the contract with a `repro` field that the relay itself executes in a sandbox before the
  ticket is forwarded, so "the ticket is a lie" stops being a residual risk.
