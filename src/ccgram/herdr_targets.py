"""Pure validation for persisted Herdr guarded-session targets."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

HERDR_SESSION_TARGET_PREFIX = "herdr-session-v1-"
_HERDR_SESSION_TARGET_RE = re.compile(
    rf"{re.escape(HERDR_SESSION_TARGET_PREFIX)}[0-9a-f]{{64}}\Z"
)


@dataclass(frozen=True)
class HerdrSessionComposite:
    """The complete input for an opaque Herdr target identity."""

    source: str
    agent: str
    kind: str
    value: str


def is_herdr_session_target(value: str) -> bool:
    """Return whether *value* is an exact v1 opaque SHA-256 target."""
    return bool(_HERDR_SESSION_TARGET_RE.fullmatch(value))


def canonical_session_bytes(composite: HerdrSessionComposite) -> bytes:
    """Return canonical UTF-8 bytes for a complete session composite."""
    values = {
        "source": composite.source,
        "agent": composite.agent,
        "kind": composite.kind,
        "value": composite.value,
    }
    if any(not isinstance(value, str) or not value for value in values.values()):
        raise ValueError("session composite is incomplete")
    # Field order is part of the persisted target-ID protocol. A golden test
    # pins it so refactors cannot silently orphan existing topic bindings.
    payload = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    return payload.encode("utf-8")


def herdr_session_target_id(composite: HerdrSessionComposite) -> str:
    """Return the opaque versioned ID for a complete session composite."""
    prefix = b"ccgram-herdr-session-v1\0"
    digest = hashlib.sha256(prefix + canonical_session_bytes(composite)).hexdigest()
    return f"{HERDR_SESSION_TARGET_PREFIX}{digest}"
