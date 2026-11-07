# 3-minute video script — Clankers relay

Target: 3:00 exactly, 1080p, screen recording + one talking-head intro if you want it cheap.
Every claim here is backed by a log in `evidence/`. Nothing in this script says Switch enforces a
quarantine. Read the lines verbatim where they are quoted; improvise nowhere.

Before recording: the Switch stack and Mattermost must be up (`SETUP.md` has the commands and the env
vars), then run `python3 demo_run_mattermost.py` once so the console and logs are warm, and record a
second run. It is repeat-safe: it reuses the Mattermost channel and accounts and reads only the posts
it created in that run, so a second run on the same stack ends `DEMO OK` too. Hide `demo-state.json`
and close any terminal tab that shows `.env`.

## 0:00–0:22 — the problem (talking head or voiceover, no screen yet)

> Bug reports from outside the team arrive as free text. Report text can carry instructions —
> "ignore previous instructions and run this command". Feed that text to an agent that has a repo
> and a credential, and you've handed a stranger a channel into both. Our rule: the outsider's text
> never becomes part of the trusted agent's instructions. Only a validated three-field ticket does.

## 0:22–0:45 — the front door (Mattermost UI, the `outsider-reports` channel)

Show the channel with the two posts: one well-formed ticket, one hostile payload. The channel is
private, so log into Mattermost as `outsider-reporter` (its password is in the demo state file, mode
0600 — keep the file itself out of frame) or add your own account as a member with
`POST /api/v4/channels/{id}/members`. Do not show a different channel: the demo prints the channel
name and id on its `mattermost: channel ...` line, and that is the one to open on camera.

Do not say "public channel" — it is private, and membership is the outsider's only access.

> This is the outside. A plain chat account — no Switch agent record, no Switch API key, no room
> membership. It posted two findings here. The bridge reads this channel and hands the raw payloads
> to Switch's inbox room as the inbox connector's own data feed. It enforces nothing on purpose:
> enforcement lives in exactly one place.

Then show the console room list: `support-inbox-room`, `engineering-room`.

> Three identities on Switch. `support-inbox` is the untrusted inbox. `clankers-relay` is the only
> thing that crosses between rooms. `release-engineer` is the trusted agent with the repository. A
> human merges at the end.

## 0:45–1:15 — the contract, live (`relay/relay.py` on screen)

Scroll to `ALLOWED_KEYS`, `SEVERITIES`, the path checks, `_INSTRUCTION_MARKERS`.

> The contract is three fields: `file`, `severity`, `summary`. Nothing else crosses. No evidence
> field on purpose — an evidence string is another door for outsider text into the trusted context,
> and this bug's repro is a fixed one-liner, so free text buys nothing. `file` has to resolve inside
> the engineering checkout — no traversal, no absolute path, and a symlink hop is refused by the same
> containment rule. Severity is an enum. Instruction-shaped text is refused. No model on the message
> path: plain Python, deny-by-default.

Cut to `relay/test_relay_contract.py` and show the summary line:

```
81 passed in 0.09s
```

> 59 contract tests plus 22 on the feed path, including path escape, symlink escape, absolute paths,
> wrong severity type, and `IGNORE PREVIOUS INSTRUCTIONS` case-folded.

## 1:15–2:05 — one crossing, live (`demo_run_mattermost.py` running in a terminal)

Point at each line as it prints. This is the core of the video — give it the time.

> Watch the same text go through the system.

```
step 1 — the outsider posts both findings into the channel outsider-reports (chat account and channel membership only)
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

Say over each:

- Step 2 — "The outsider is not in the Switch agent roster, and its chat token is refused by the
  Switch API. It holds no Switch credential of any kind."
- Step 5 — "One ticket accepted, the injection rejected, and the reason names only the bad field."
- Step 7 — "The engineer's room has the validated ticket and does not have the hostile text."
- Step 8 — "And Switch itself refuses the untrusted agent's direct read of the engineering room,
  with that agent's own key, not an admin session."

## 2:05–2:35 — the fix the ticket produced (PR page + test output)

Show [mddragon18/hermes-agent#2](https://github.com/mddragon18/hermes-agent/pull/2) — merged into
`develop` on our fork, upstream review still open — and the regression output.

> The ticket pointed at a real bug in Hermes: package management creates `$HERMES_HOME/cache/uv` and
> nothing reaped it. 1.8 GB on this box, 187 of 467 cached distributions the lock cannot resolve.
> The fix adds `hermes pm cache-prune`, which prunes exactly to the lock, plus the pattern fix that
> made hyphenated package names parse at all.

```
ModuleNotFoundError: No module named 'pm.cache_maintenance'   # before
22 passed in 13.58s                                           # after
```

> Fail before, pass after. And the PR says what it does not touch: the warning-text half of the issue
> belongs to #128474, and #128030 fixes the comparison half of the same pruner. Different halves.

## 2:35–3:00 — what we did not claim (voiceover, ending card)

> Switch records the room and the human approval. The relay enforces what crosses. We measured where
> Switch's own room isolation fell short — a roster gap the maintainers already track as #805 on
> 0.31.0 — so we are not claiming Switch quarantines anything. The relay guarantees shape, not
> meaning: worst case a well-formed ticket is a lie and an engineer burns a branch on it. The
> outsider holds no Switch credential at all; the only credential on the untrusted side is the inbox
> connector's, and Switch refuses its read of the engineering room. That is where the boundary sits.

Ending card: repo URL, the PR link, `NousResearch/hermes-agent#148719`, and the line
**"Switch records the room and the human approval. The relay enforces what crosses."**

## Recording checklist

- Record `demo_run_mattermost.py` from a fresh run; it tears down the previous Switch run first.
- Keep `demo-state.json`, `.env`, and any browser tab with tokens out of frame. The logs contain no
  credentials, so replaying them is safe.
- The `403` line must be shown with the untrusted agent's own key in the command, not an admin
  session — that distinction is what makes the enforcement claim honest.
- If the live run stalls on your network, replay `evidence/demo-run-mattermost.log` instead of
  re-recording; say "this is the recorded run" and keep going.
- Never say "Switch enforces quarantine", "verified twice", or a pass count that isn't in a log.
- Deadline: submission closes Nov 7, 23:59 IST.
