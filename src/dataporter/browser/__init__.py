"""The browser our tool owns.

`07` built the base: a Chrome launched with a dedicated profile inside the
workspace (`launcher`), a minimal synchronous CDP client (`cdp`), the one place
that knows what claude.ai looks like (`probe`) and the operator-facing flows
`login` and `session …` are made of (`session`).

`08` adds `helpers`: the deterministic primitives Hermes calls through its
terminal tool — probe, paste, attach, await, close extra tabs. They are built on
these and add nothing to them: everything in this package is our own code,
driven by us, and never by an LLM.
"""

from dataporter.browser.cdp import CdpClient, Connection, Page, Target
from dataporter.browser.helpers import (
    CLAUDE,
    MIGRATION_SURFACE,
    Emission,
    Outcome,
    PasteMethod,
    Surface,
)
from dataporter.browser.launcher import (
    BrowserSession,
    PortInUseError,
    find_executable,
    launch,
)
from dataporter.browser.probe import LastMessage, PageKind, PageState, PageView

__all__ = [
    "CLAUDE",
    "MIGRATION_SURFACE",
    "BrowserSession",
    "CdpClient",
    "Connection",
    "Emission",
    "LastMessage",
    "Outcome",
    "Page",
    "PageKind",
    "PageState",
    "PageView",
    "PasteMethod",
    "PortInUseError",
    "Surface",
    "Target",
    "find_executable",
    "launch",
]
"""`probe` — the function — is deliberately not re-exported: binding that name
here would shadow the `dataporter.browser.probe` module for anyone who writes
`from dataporter.browser import probe`. Import it from its own module."""
