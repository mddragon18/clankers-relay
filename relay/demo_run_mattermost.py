#!/usr/bin/env python3
"""Clankers demo with the real front door wired: Mattermost channel -> ingest bridge -> Switch
inbox room -> contract relay -> engineering room -> (human merge, out of band).

Difference from `demo_run.py`: the outsider text arrives through Mattermost, so the outsider
account holds a chat credential only. It has no Switch agent record, no Switch API key, and no
room membership. This run proves that with three live checks:

  1. the outsider posts two findings into a public Mattermost channel,
  2. the bridge (`mattermost_feed.py`) moves the raw payloads into the Switch inbox room using the
     `support-inbox` agent key — the bridge is that agent's connector, not the outsider's key,
  3. the outsider's own Mattermost token is refused by the Switch API (401), and `support-inbox`
     is refused the engineering room by Switch (403).

The relay is unchanged: it validates `{file, severity, summary}` and forwards only accepted tickets.

Env vars (same as demo_run.py, plus Mattermost ones): SWITCH_BASE, SWITCH_ENV_FILE, DEMO_STATE_FILE,
DEMO_LOG_FILE, ENGINEERING_REPO, MATTERMOST_BASE (default http://127.0.0.1:8065).
Credential values go to demo-state.json (mode 0600) and are never printed.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import demo_run as D  # noqa: E402  reuse the Switch-side helpers, unchanged
from mattermost_feed import (mm_account_with_login, mm_add_to_channel, mm_add_to_team, mm_call,
                             mm_ensure_public_channel, mm_findings_since, mm_login, mm_post_capture,
                             mm_team_id)  # noqa: E402

MM_BASE = os.environ.get("MATTERMOST_BASE", "http://127.0.0.1:8065")
CHANNEL_NAME = "outsider-reports"
OUTSIDER = "outsider-reporter"
FEED_USER = "clankers-feed"


def main() -> int:
    lines: list[str] = []

    def say(text):
        print(text)
        lines.append(text)

    s, _b, cookie = D.http_cookie(f"{D.BASE}/gateway/auth/login", "POST",
                                  {"email": D.env("GATEWAY_ADMIN_EMAIL"),
                                   "password": D.env("GATEWAY_ADMIN_PASSWORD")})
    if s != 200:
        raise SystemExit(f"gateway admin login failed: {s}")

    say("teardown of any previous demo run (Switch side)")
    D.teardown(cookie, say)

    # --- Switch side: three identities, two rooms (identical to demo_run.py) ---
    s, b = D.http(f"{D.BASE}/gateway/api-keys", "POST", {"label": "clankers-demo-owner"}, cookie=cookie)
    if s not in (200, 201):
        raise SystemExit(f"mint owner key: {s} {b[:120]}")
    owner_key = D.find(json.loads(b), {"key", "api_key", "token"})

    inbox = D.register("support-inbox", D.env("AGENT_REGISTRATION_TOKEN"))
    engineer = D.register("release-engineer", owner_key)
    relay_agent = D.register("clankers-relay", owner_key)
    inbox_room = D.create_room(inbox, "support-inbox-room", ["support-inbox", "clankers-relay"])
    eng_room = D.create_room(engineer, "engineering-room", ["release-engineer", "clankers-relay"])
    say(f"agents: support-inbox={inbox['id']} release-engineer={engineer['id']} "
        f"clankers-relay={relay_agent['id']}")
    say(f"rooms: support-inbox-room={inbox_room['id']} engineering-room={eng_room['id']}")

    # --- Mattermost side: the front door ---
    mm_admin = mm_login(MM_BASE, D.env("MATTERMOST_ADMIN_USER"), D.env("MATTERMOST_ADMIN_PASSWORD"))
    team = mm_team_id(MM_BASE, mm_admin)
    channel_id, created = mm_ensure_public_channel(MM_BASE, mm_admin, CHANNEL_NAME, "Outsider Reports")
    # Passwords are generated once and kept in the state file (mode 0600): the accounts persist across
    # runs and this Mattermost build has no admin password-reset endpoint, so a fresh password each
    # run would lock us out of our own accounts.
    mm_saved = {}
    if D.STATE.exists():
        try:
            mm_saved = json.loads(D.STATE.read_text()).get("mattermost", {})
        except Exception:
            mm_saved = {}
    outsider_pw = mm_saved.get("outsider_password") or secrets.token_urlsafe(18)
    feed_pw = mm_saved.get("feed_password") or secrets.token_urlsafe(18)
    outsider_id, outsider_tok = mm_account_with_login(MM_BASE, mm_admin, OUTSIDER,
                                                       f"{OUTSIDER}@local", outsider_pw,
                                                       "outside reporter", team)
    feed_id, feed_tok = mm_account_with_login(MM_BASE, mm_admin, FEED_USER, f"{FEED_USER}@local",
                                              feed_pw, "clankers ingest bridge", team)
    say(f"\nmattermost: channel {CHANNEL_NAME}={'created' if created else 'reused'} id={channel_id[:8]}, "
        f"users {OUTSIDER}={outsider_id[:8]} {FEED_USER}={feed_id[:8]}")
    say(f"  team membership: {OUTSIDER}={mm_add_to_team(MM_BASE, mm_admin, outsider_id, team)}, "
        f"{FEED_USER}={mm_add_to_team(MM_BASE, mm_admin, feed_id, team)}")
    say(f"  channel membership: {OUTSIDER}={mm_add_to_channel(MM_BASE, mm_admin, channel_id, outsider_id)}, "
        f"{FEED_USER}={mm_add_to_channel(MM_BASE, mm_admin, channel_id, feed_id)}")

    say("\nstep 1 — the outsider posts both findings into the public channel (chat account only)")
    s1, at1 = mm_post_capture(MM_BASE, outsider_tok, channel_id, f"FINDING {D.TICKET}")
    s2, at2 = mm_post_capture(MM_BASE, outsider_tok, channel_id, f"FINDING {D.HOSTILE}")
    say(f"  posted well-formed={s1} hostile={s2}")

    say("\nstep 2 — the outsider's chat token is not a Switch credential")
    roster = [r.strip() for r in D.psql("SELECT name FROM agents").splitlines() if r.strip()]
    say(f"  Switch agent roster: {', '.join(roster) if roster else '(none)'}")
    say(f"  outsider-reporter registered as a Switch agent: {'outsider-reporter' in roster}")
    s, b = D.http(f"{D.BASE}/agents/{inbox['id']}/rooms/{inbox_room['id']}/history?limit=5",
                  headers={"Authorization": f"Bearer {outsider_tok}"})
    say(f"  Switch API with the Mattermost token: {s} {b[:60]}")
    mm_token_refused = s == 401
    outsider_has_no_agent_record = "outsider-reporter" not in roster

    say("\nstep 3 — the ingest bridge reads the channel and hands raw payloads to Switch")
    # Feed cursor: the posts this run created, one millisecond back. Mattermost's `since` is exclusive
    # and filtered on its own clock, so taking the wall clock here could drop the first post.
    since_ms = (min(at1, at2) - 1) if (at1 and at2) else 0
    raws: list[str] = []
    for attempt in range(20):
        raws = mm_findings_since(MM_BASE, feed_tok, channel_id, since_ms)
        if len(raws) >= 2:
            break
        time.sleep(2.0)
    say(f"  bridge read {len(raws)} finding payload(s) from the channel after {attempt + 1} poll(s)")
    for raw in raws[:2]:
        s, _ = D.post(inbox, inbox_room["id"], f"FINDING {raw}")
        say(f"  bridge forwarded raw payload into inbox room: {s}")

    say("\nstep 4 — the relay reads the inbox room with its OWN credential")
    payloads: list[str] = []
    for attempt in range(60):
        s, b = D.history(relay_agent, inbox_room["id"])
        j = json.loads(b)
        events = j.get("events", []) if isinstance(j, dict) else j
        payloads = [m["body"][len("FINDING "):] for m in events
                    if isinstance(m, dict) and m.get("body", "").startswith("FINDING ")]
        if len(payloads) >= 2:
            break
        time.sleep(2.0)
    say(f"  relay read: {s} after {attempt + 1} poll(s), {len(payloads)} payload(s)")

    say("\nstep 5 — the contract relay validates each payload against the engineering repo")
    forwarded: list[dict] = []
    for raw in payloads[:2]:
        try:
            ticket = D.validate_json(raw, D.REPO)
            say(f"  ACCEPTED file={ticket['file']} severity={ticket['severity']}")
            forwarded.append(ticket)
        except D.Reject as exc:
            say(f"  REJECTED ({exc})")

    say("\nstep 6 — the relay forwards only validated `{file, severity, summary}`")
    for ticket in forwarded:
        forward = json.dumps(ticket, sort_keys=True)
        s, _ = D.post(relay_agent, eng_room["id"], f"RELAY {forward}")
        say(f"  forwarded into engineering room: {s} {forward}")

    say("\nstep 7 — the trusted engineer reads its room")
    crossed = leaked = False
    for attempt in range(30):
        s, b = D.history(engineer, eng_room["id"])
        crossed = "cache/uv grows forever" in b
        leaked = "ignore previous instructions" in b
        if crossed:
            break
        time.sleep(2.0)
    say(f"  engineer read: {s} after {attempt + 1} poll(s)")
    say(f"  engineering room shows the validated ticket: {crossed}")
    say(f"  engineering room shows the hostile text: {leaked}")

    say("\nstep 8 — Switch refuses the untrusted agent's direct read of the engineering room")
    refused_status, body = D.history(inbox, eng_room["id"])
    say(f"  support-inbox direct read: {refused_status} {body[:70]}")

    state = {"agents": {"support-inbox": inbox, "release-engineer": engineer,
                        "clankers-relay": relay_agent},
             "rooms": {"inbox": inbox_room, "engineering": eng_room},
             "mattermost": {"base": MM_BASE, "channel_name": CHANNEL_NAME, "channel_id": channel_id,
                            "outsider_user_id": outsider_id, "feed_user_id": feed_id,
                            "outsider_password": outsider_pw, "feed_password": feed_pw}}
    D.STATE.write_text(json.dumps(state, indent=2))
    os.chmod(D.STATE, 0o600)

    ok = (crossed and not leaked and refused_status == 403 and len(forwarded) == 1
          and mm_token_refused and outsider_has_no_agent_record and len(raws) == 2)
    say("\nRESULT: " + ("DEMO OK — the outsider's report entered through Mattermost with no Switch "
                        "credential; the bridge carried it as data; the relay validated one ticket "
                        "and refused the injection; Switch refused every direct cross-room read"
                        if ok else "DEMO INCOMPLETE — see the lines above"))
    D.LOG.write_text("\n".join(lines) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
