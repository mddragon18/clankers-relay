#!/usr/bin/env python3
"""Mattermost ingest bridge: the front door for outsiders who hold no Switch credential.

Why this file exists. Track 01's story is "bug reports arrive from outside the team". In the real
deployment an outsider signs into the chat front end (Mattermost) and has no Switch agent record,
no Switch API key, and no room membership anywhere. This bridge is the inbox agent's connector:
it holds a Mattermost token plus the `support-inbox` agent key, moves raw finding payloads from a
public channel into the Switch inbox room verbatim, and does no enforcement of its own.

Enforcement stays in the relay (`relay.py`), which is the only component that crosses into the
engineering room. The bridge deliberately forwards unvalidated text: it is transport, so the
contract decision happens in exactly one place and that place is testable (see
`test_relay_contract.py`).

Endpoints on this build are the v4 subset Switch ships: login takes `login_id`; channel creation
and membership are `POST /api/v4/channels`, `POST /api/v4/teams/{team}/members`,
`POST /api/v4/channels/{channel}/members`; the feed is
`GET /api/v4/channels/{channel}/posts?since=<unix ms>` returning `{order, posts}`. There is no
archive/delete endpoint in this image, so repeat runs reuse the same channel and rely on `since`.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

FINDING_PREFIX = "FINDING "


def mm_call(base: str, path: str, method: str = "GET", body=None, token: str | None = None):
    """Return `(status, text, token_or_empty)`. Token comes from the `Token` response header."""
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode(), r.headers.get("Token", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200], ""


def mm_login(base: str, login_id: str, password: str) -> str:
    s, b, tok = mm_call(base, "/api/v4/users/login", "POST",
                        {"login_id": login_id, "password": password})
    if s != 200 or not tok:
        raise RuntimeError(f"mattermost login for {login_id}: {s} {b[:120]}")
    return tok


def mm_team_id(base: str, token: str) -> str:
    s, b, _ = mm_call(base, "/api/v4/users/me/teams", token=token)
    if s != 200:
        raise RuntimeError(f"teams lookup: {s} {b[:120]}")
    teams = json.loads(b)
    if not teams:
        raise RuntimeError("no teams visible to this account")
    return teams[0]["id"]


def mm_ensure_public_channel(base: str, admin_token: str, name: str, display_name: str):
    """Create the channel, or find the existing one. Returns `(channel_id, created_bool)`."""
    team = mm_team_id(base, admin_token)
    s, b, _ = mm_call(base, "/api/v4/channels", "POST",
                      {"team_id": team, "name": name, "display_name": display_name, "type": "P",
                       "purpose": "untrusted outsider bug reports"}, token=admin_token)
    if s in (200, 201):
        return json.loads(b)["id"], True
    # Already exists (or created by an earlier run): look it up in the caller's channel list.
    s, b, _ = mm_call(base, f"/api/v4/users/me/teams/{team}/channels", token=admin_token)
    if s == 200:
        for c in json.loads(b):
            if c["name"] == name:
                return c["id"], False
    raise RuntimeError(f"channel {name} unavailable: create={s}, lookup={b[:120]}")


def mm_ensure_user(base: str, admin_token: str, username: str, email: str, password: str,
                   nickname: str, team_id: str):
    """Create a Mattermost account, or reuse the existing one. Passwords for reused accounts are the
    caller's business: this build has no admin password-reset endpoint, so the demo keeps the password
    it created the account with. Returns `user_id`."""
    s, b, _ = mm_call(base, "/api/v4/users", "POST",
                      {"username": username, "email": email, "password": password,
                       "nickname": nickname}, token=admin_token)
    if s in (200, 201):
        return json.loads(b)["id"]
    s, b, _ = mm_call(base, f"/api/v4/users/username/{username}", token=admin_token)
    if s == 200:
        return json.loads(b)["id"]
    raise RuntimeError(f"mattermost user {username}: create {s} {b[:120]}")


def mm_delete_permanently(base: str, admin_token: str, user_id: str) -> int:
    """Permanent delete of a demo account (system admin). Frees the username so it can be recreated.
    `DELETE /api/v4/users/{id}/permanent`."""
    s, _b, _ = mm_call(base, f"/api/v4/users/{user_id}/permanent", "DELETE", token=admin_token)
    return s


def mm_account_with_login(base: str, admin_token: str, username: str, email: str, password: str,
                          nickname: str, team_id: str):
    """Return `(user_id, session_token)`. Reuses an existing account when its password matches ours.
    If it doesn't — a stale account from an interrupted run whose password we lost — delete it
    permanently and create a fresh one: this build has no admin password-reset endpoint, so that is
    the only way to hand the account a password we know."""
    uid = mm_ensure_user(base, admin_token, username, email, password, nickname, team_id)
    try:
        return uid, mm_login(base, username, password)
    except RuntimeError:
        mm_delete_permanently(base, admin_token, uid)
        s, b, _ = mm_call(base, "/api/v4/users", "POST",
                          {"username": username, "email": email, "password": password,
                           "nickname": nickname}, token=admin_token)
        if s not in (200, 201):
            raise RuntimeError(f"mattermost recreate {username}: {s} {b[:120]}")
        return json.loads(b)["id"], mm_login(base, username, password)


def mm_add_to_team(base: str, admin_token: str, user_id: str, team_id: str) -> int:
    s, _b, _ = mm_call(base, f"/api/v4/teams/{team_id}/members", "POST",
                       {"user_id": user_id, "team_id": team_id}, token=admin_token)
    return s


def mm_add_to_channel(base: str, admin_token: str, channel_id: str, user_id: str) -> int:
    s, _b, _ = mm_call(base, f"/api/v4/channels/{channel_id}/members", "POST",
                       {"channel_id": channel_id, "user_id": user_id}, token=admin_token)
    return s


def mm_post_capture(base: str, token: str, channel_id: str, message: str):
    """Post and return `(status, create_at_ms)` from the created post. The caller uses `create_at` as
    the feed cursor: Mattermost filters `since` on its own clock, and the two machines can disagree by
    a few milliseconds, which would drop the first post of the run."""
    s, b, _ = mm_call(base, "/api/v4/posts", "POST",
                      {"channel_id": channel_id, "message": message}, token=token)
    create_at = 0
    if s in (200, 201):
        try:
            create_at = int(json.loads(b).get("create_at", 0))
        except (ValueError, TypeError):
            create_at = 0
    return s, create_at


def mm_post(base: str, token: str, channel_id: str, message: str) -> int:
    s, _b, _ = mm_call(base, "/api/v4/posts", "POST",
                       {"channel_id": channel_id, "message": message}, token=token)
    return s


def mm_findings_since(base: str, token: str, channel_id: str, since_ms: int) -> list[str]:
    """Raw finding payloads posted to the channel after `since_ms`, oldest first.

    The feed payload is `{order: [post_id], posts: {post_id: post}}`. Messages that do not start
    with `FINDING ` are ignored: this bridge only carries finding payloads, and it hands them over
    untouched — validation belongs to the relay.
    """
    s, b, _ = mm_call(base, f"/api/v4/channels/{channel_id}/posts?since={since_ms}&limit=200",
                      token=token)
    if s != 200:
        raise RuntimeError(f"channel feed read: {s} {b[:120]}")
    j = json.loads(b)
    posts = j.get("posts", {})
    out: list[str] = []
    for pid in j.get("order", []):
        p = posts.get(pid)
        if not isinstance(p, dict):
            continue
        msg = p.get("message", "")
        if msg.startswith(FINDING_PREFIX):
            out.append(msg[len(FINDING_PREFIX):])
    # `order` is newest-first on this build; reverse so the inbox sees them in posting order.
    return list(reversed(out))
