"""The browser our tool owns.

`07` is the whole of this package for now: a Chrome launched with a dedicated
profile inside the workspace (`launcher`), a minimal synchronous CDP client
(`cdp`), the one place that knows what claude.ai looks like (`probe`) and the
operator-facing flows `login` and `session …` are made of (`session`).

`08` adds the helpers Hermes calls through its terminal tool. They are built on
these primitives and add nothing to them: everything in this package is our own
code, driven by us, and never by an LLM.
"""

from dataporter.browser.cdp import CdpClient, Connection, Page, Target
from dataporter.browser.launcher import (
    BrowserSession,
    PortInUse,
    find_executable,
    launch,
)
from dataporter.browser.probe import PageKind, PageState

__all__ = [
    "BrowserSession",
    "CdpClient",
    "Connection",
    "Page",
    "PageKind",
    "PageState",
    "PortInUse",
    "Target",
    "find_executable",
    "launch",
]
"""`probe` — the function — is deliberately not re-exported: binding that name
here would shadow the `dataporter.browser.probe` module for anyone who writes
`from dataporter.browser import probe`. Import it from its own module."""
