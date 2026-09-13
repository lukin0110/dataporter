"""Who is signed in, and who is half-way there.

A session is a token the site minted at sign-in and the browser carries in a
cookie; it lives until the process does (§21, *Lifetime*), and the cookie it
rides in has a lifetime of its own (`wire.SESSION_MAX_AGE_S`) so that closing
Chrome does not end it. A sign-in is more than one request, and what joins
them is a token this server minted — a cookie between the email step and the
password step, or a one-time code between one host and another — so the
half-finished sign-ins are kept here too, apart from the site's chats.
"""

import secrets
import threading


class Sessions:
    """The tokens that are signed in, behind a lock."""

    def __init__(self) -> None:
        self._tokens: set[str] = set()
        self._lock = threading.Lock()

    def open(self) -> str:
        """Mint a session. The site counts it: a sign-in is the site's verb."""
        token = secrets.token_hex(16)
        with self._lock:
            self._tokens.add(token)
        return token

    def holds(self, token: str | None) -> bool:
        if not token:
            return False
        with self._lock:
            return token in self._tokens

    def close(self, token: str | None) -> None:
        with self._lock:
            self._tokens.discard(token or "")


class Pending:
    """The half-finished sign-ins a server is holding: a token each, and the address behind it."""

    def __init__(self) -> None:
        self._pending: dict[str, str] = {}
        self._lock = threading.Lock()

    def new_token(self) -> str:
        return secrets.token_hex(8)

    def remember(self, token: str, email: str) -> None:
        with self._lock:
            self._pending[token] = email

    def pending(self, token: str | None) -> str:
        with self._lock:
            return self._pending.get(token or "", "")

    def forget(self, token: str | None) -> None:
        with self._lock:
            self._pending.pop(token or "", None)
