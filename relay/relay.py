"""The Clankers relay: the deterministic boundary between the untrusted support inbox and the
trusted engineering room.

Contract (team decision, Nov 2026): a finding is `{file, severity, summary}` and nothing else.
No free-text `evidence` field — anything the inbox agent can put in a payload beyond these
three fields is text that would land in the trusted agent's context, so the contract refuses it.
The file is validated against the repository root (no escape, no symlink hop, no absolute path)
and severity is normalized to a fixed vocabulary. Validation is deterministic plain Python: no
LLM, no shell, no git. The relay is a plain service, not a Switch agent — it is the only
component that crosses rooms, and it shares one Switch connection with filter=all (its own
memberships, never another agent's).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

ALLOWED_KEYS = frozenset({"file", "severity", "summary"})
SEVERITIES = ("low", "medium", "high", "critical")

# A summary that reads like an instruction is data with ambitions. It stays out of the trusted
# room: the trusted agent's own prompt is the only instruction channel.
_INSTRUCTION_MARKERS = (
    "ignore previous", "ignore all previous", "ignore the", "disregard", "forget previous",
    "disregard previous", "system prompt", "your instructions", "new instructions",
    "run ", "execute ", "curl ", "wget ", "rm -", "sudo ", "git push", "git commit",
    "cat ", "read file", "then run", "now run",
)
_SHELL_MARKERS = ("$(", "`", "; rm", "&&", "||")

# `file` must be a repo-relative path made of ordinary path characters: no absolute path, no
# parent traversal, no NUL, no control characters.
_PATH_SAFE = re.compile(r"^[A-Za-z0-9._+\-@/]+$")
_MAX_SUMMARY = 400
_MAX_FILE = 200


class Reject(Exception):
    """Raised with the reason a payload was refused. The reason is safe to echo to the inbox."""


def _reject(reason: str) -> "Reject":
    return Reject(reason)


def validate(payload: Any, repo_root: Path) -> dict:
    """Return the normalized ticket `{file, severity, summary}` or raise `Reject`.

    *repo_root* is the repository the finding is about: `file` is resolved inside it and must
    exist as a regular file, so a report cannot point at a path outside the checkout.
    """
    if not isinstance(payload, dict):
        raise _reject(f"payload must be an object, got {type(payload).__name__}")
    extra = set(payload) - ALLOWED_KEYS
    if extra:
        raise _reject(f"unknown field(s) in contract: {', '.join(sorted(extra))}")
    missing = ALLOWED_KEYS - set(payload)
    if missing:
        raise _reject(f"missing field(s): {', '.join(sorted(missing))}")

    file_ = payload["file"]
    severity = payload["severity"]
    summary = payload["summary"]
    if not isinstance(file_, str) or not isinstance(summary, str) or not isinstance(severity, str):
        raise _reject("file, severity and summary must all be strings")

    file_ = file_.strip()
    if not file_ or len(file_) > _MAX_FILE:
        raise _reject(f"file must be between 1 and {_MAX_FILE} characters")
    if not _PATH_SAFE.match(file_):
        raise _reject("file contains characters outside an ordinary repo-relative path")
    if file_.startswith("/") or file_.startswith("\\") or re.match(r"^[A-Za-z]:[\\/]", file_):
        raise _reject("file must be repository-relative, not absolute")
    if any(part == ".." for part in file_.split("/")):
        raise _reject("file may not traverse parent directories")

    repo = Path(os.path.realpath(repo_root))
    # `realpath` follows every link, so containment is checked on the final target: a symlink
    # hop out of the checkout is refused by the same rule as an absolute path.
    target = os.path.realpath(repo / file_)
    if not target.startswith(str(repo) + os.sep):
        raise _reject("file resolves outside the repository")
    if not os.path.isfile(target):
        raise _reject(f"file does not exist in the repository: {file_}")

    sev = severity.strip().lower()
    if sev not in SEVERITIES:
        raise _reject(f"severity must be one of {', '.join(SEVERITIES)}")

    text = " ".join(summary.split())
    if not text:
        raise _reject("summary is empty")
    if len(text) > _MAX_SUMMARY:
        raise _reject(f"summary exceeds {_MAX_SUMMARY} characters")
    lowered = text.lower()
    if any(marker in lowered for marker in _INSTRUCTION_MARKERS):
        raise _reject("summary looks like an instruction, not a description")
    if any(marker in text for marker in _SHELL_MARKERS):
        raise _reject("summary contains shell syntax")

    return {"file": str(Path(target).relative_to(repo)), "severity": sev, "summary": text}


def validate_json(raw: str | bytes, repo_root: Path) -> dict:
    """`validate()` for a raw JSON string — what arrives over the wire."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _reject(f"payload is not valid JSON: {exc.msg}") from exc
    return validate(payload, repo_root)
