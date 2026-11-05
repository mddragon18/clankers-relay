# Clankers relay — the crossing component

Switch records the room and the human approval. The relay enforces what crosses. We measured
where Switch's own room isolation fell short: a roster gap on 0.31.0 where `POST
/agents/{id}/moderation/rooms` accepts foreign agent names, tracked upstream as known roster gap
#805 on 0.31.0. Direct cross-room reads, posts and history are enforced by Switch and return 403;
the HTTP 500 on authorization refusals exists only on the pinned 0.31.0 image's legacy moderation
route and is not generalized to anything else.

## The contract

An untrusted support-inbox agent posts a finding payload into its own room. The relay validates
it and forwards **exactly three fields** to the engineering room:

```json
{"file": "...", "severity": "...", "summary": "..."}
```

Nothing else crosses. No free-text `evidence` field on purpose: an evidence string is outsider
text straight into the trusted agent's context, and this target's repro is a fixed one-liner
(`du -sh ~/.hermes/cache/uv`), so free text buys nothing. The relay is deterministic plain
Python — no model on the message path — and rejects:

- keys other than `file`, `severity`, `summary`
- a `file` that does not resolve inside the engineering repo (path traversal, absolute paths,
  escaping the repo root)
- instruction-shaped `summary` text ("ignore previous instructions", shell pipelines, URLs)
- severity outside `blocker|critical|high|medium|low`

## Roles on the live stack

| identity | owner | rooms |
|---|---|---|
| `support-inbox` | registration token (Agent Bootstrap) | its own room only |
| `clankers-relay` | minted owner API key | both rooms, on its own memberships, filter=all |
| `release-engineer` | minted owner API key | engineering room only |

The relay is one connection, a member of both rooms, filtering every message it reads. It never
borrows another agent's credential or placement.

## Run it

```bash
cd /home/md/switch-relay/contract
python3 -m pytest -q test_relay_contract.py     # the contract tests
python3 demo_run.py                             # live stack: end-to-end crossing
```

`demo_run.py` registers the three identities, creates the two rooms, posts one well-formed ticket
and one hostile payload as the untrusted agent, and records: the relay read, each verdict, what
the engineer actually sees, and the untrusted agent's refused direct read. Teardown runs first, so
the run is reproducible. Credential material lands only in `demo-state.json` (mode 0600) and never
in the log.

Evidence in `~/Documents/switch-evidence/`: `demo-run.log` (the run), `recheck-2026-11-05.log`
(the corrected measurement), `hermes-fix-red.log` / `hermes-fix-green.log` (fail-before and
pass-after for the Hermes fix).
