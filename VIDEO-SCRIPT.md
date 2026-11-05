# 3-minute video script

Target length: 3:00. Every claim below is backed by a log in `evidence/` — the script never says
something we did not measure. Nothing in this script says Switch enforces a quarantine.

## 0:00–0:25 — the problem

> Bug reports from outsiders arrive as free text. If you feed that text to a capable agent, you
> have given that stranger a channel into a repository and a credential. Our rule: the outsider's
> text never becomes part of the trusted agent's instructions.

Say it, don't show it yet.

## 0:25–0:55 — the shape of the workflow

Show the room list in Mattermost / Switch console: `support-inbox-room`, `engineering-room`.

> Three identities. `support-inbox` is untrusted and holds no Switch credential of ours — its text
> arrives through Mattermost. `clankers-relay` is a protocol agent and the only thing that crosses
> between the rooms. `release-engineer` is the trusted agent with the repository. A human merges.

## 0:55–1:30 — the contract, live

Terminal, `relay/relay.py`, show the field list.

> The contract is three fields: `file`, `severity`, `summary`. Nothing else crosses. No evidence
> field on purpose — a free-text evidence field is just another door for outsider text into the
> trusted context. The path is validated against the engineering repository, severity is an enum,
> and instruction-shaped text is refused. No model on the message path: plain Python.

Show the relay's two verdicts from the demo run:

```
ACCEPTED file=pm/packages.py severity=high
REJECTED (unknown field(s) in contract: evidence)
```

## 1:30–2:10 — one ticket crossing

Run `python3 demo_run.py` (or replay the log). Point at each line as it appears.

> The relay reads the inbox with its own credential, validates both payloads, and forwards only the
> accepted ticket. The engineer's room contains the validated ticket and does **not** contain the
> hostile text:
>
> ```
> engineering room shows the validated ticket: True
> engineering room shows the hostile text: False
> direct cross-room read by support-inbox: 403 Agent is not a member of this room
> ```

## 2:10–2:40 — the fix it produced

Show the merged PR and the regression test output.

> The ticket pointed at a real bug in `hermes-agent`: PM creates `$HERMES_HOME/cache/uv` and nothing
> reaped it — 1.8 GB on this box, 187 of 467 cached distributions the lock cannot resolve. The fix
> adds `hermes pm cache-prune`, which prunes exactly to the lock, plus the fix for a cache-marker
> pattern that silently kept superseded dists with hyphenated names.
>
> ```
> ModuleNotFoundError: No module named 'pm.cache_maintenance'   # before
> 22 passed in 13.58s                                            # after
> ```

## 2:40–3:00 — what we did not claim

Say this plainly; it's the credibility of the whole entry.

> Switch records the room and the human approval. The relay enforces what crosses. We measured
> where Switch's own room isolation fell short — a roster gap the maintainers already track as #805
> on 0.31.0 — so we are not claiming Switch quarantines anything. The relay guarantees shape, not
> meaning: worst case a well-formed ticket is a lie and the engineer burns a branch on it. The
> untrusted side holds no Switch credential at all, which is why the boundary holds.

## Ending card

Repo URL, the merged PR link, upstream issue `NousResearch/hermes-agent#148719`, and the line
`Switch records the room and the human approval. The relay enforces what crosses.`

## Recording notes

- Run `demo_run.py` fresh — it tears down the previous run first, so the rooms and agents are clean.
- Keep `demo-state.json` out of frame; credentials are in a `0600` file and never enter the log.
- Record the `403` line with the untrusted agent's own key visible in the command, not an admin
  session — that distinction is what makes the enforcement claim honest.
