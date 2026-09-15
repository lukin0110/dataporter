"""The runner playing the person a sign-in by link needs (`49`, brief 07 §73).

`login` opens a window at the mock's sign-in page and waits for a person to
enter the account's address there; a rehearsal has no person. So the runner
does the one thing the person would do, the way the tool's own credential seam
does it (`24`): it attaches to the Chrome the tool launched, on the debug port
the tool's own `config.toml` names, dismisses the banner, puts the address into
the email field through `Input.insertText`, and presses Enter. Then it waits
for the page to say the link is on its way — the same control the tool reads —
and reads the link from the listing that stands in for the inbox.

Nothing here is an agent, and nothing here is the tool: it is the keyboard.
"""

import time
import tomllib
from pathlib import Path

from dataporter.browser.cdp import CdpClient, Page
from rehearsal import run as running

SIGN_IN_LINKS_JSON_PATH = "/__mock/sign-in-links.json"
"""The mock's listing of the links it minted, re-typed rather than imported:
the rehearsal drives the mock as an operator would and imports nothing from it
(ADR 0003), as `extraction.EXPORTS_JSON_PATH` is."""

PERSON_S = 90.0
"""How long the runner waits for the tool's window to show the email field:
Chrome starting, the mock's page loading, the banner. Generous, because a
timeout here fails a rehearsal and a slow machine should not."""

LINK_SENT_S = 20.0
"""How long the runner waits, after Enter, for the page to show the code field."""

POLL_S = 0.25

SIGN_IN_PATH = "/login"

ADDRESS_JS = """\
(() => {
  const visible = (el) => !!(el && el.offsetParent !== null);
  const accept = document.getElementById('accept-cookies');
  if (visible(accept)) accept.click();
  const field = document.querySelector('input[type="email"]');
  if (!visible(field)) return 'not yet';
  field.focus();
  field.select();
  return document.activeElement === field ? 'ready' : 'unfocused';
})()
"""
"""One look: the banner dismissed if it is there, and the email field focused
if it is showing. The value goes in afterwards, as a CDP parameter."""

LINK_SENT_JS = """\
(() => {
  const field = document.querySelector('input[autocomplete="one-time-code"]');
  return !!(field && field.offsetParent !== null);
})()
"""
"""Whether the page shows the link has been sent: the tool's own `link sent`
row, read the way the tool reads it."""


class PersonError(RuntimeError):
    """The runner could not do what a person would have: the window never came, or the field did not."""


def cdp_port_of(workspace: Path) -> int:
    """Return the debug port the tool's own configuration names for this workspace."""
    loaded = tomllib.loads((workspace / "config.toml").read_text(encoding="utf-8"))
    return int(loaded["browser"]["cdp_port"])


def enter_address(workspace: Path, email: str, *, timeout_s: float = PERSON_S, poll_s: float = POLL_S) -> None:
    """Type the address into the tool's sign-in window and press Enter, then wait for the link-sent page.

    Polls until the tool's Chrome answers its debug port and shows the mock's
    sign-in page with its email field, which is what a person would be looking
    at. `PersonError` on the deadline, with what was seen last.
    """
    port = cdp_port_of(workspace)
    client = CdpClient(port=port, timeout=30.0)
    deadline = time.monotonic() + timeout_s
    seen = "no browser on the port"
    while True:
        if client.responding():
            page = _sign_in_tab(client)
            if page is None:
                seen = "no sign-in tab"
            else:
                try:
                    answer = page.evaluate(ADDRESS_JS)
                    if answer == "ready":
                        page.insert_text(email)
                        page.press_enter()
                        _await_link_sent(client, deadline=time.monotonic() + LINK_SENT_S, poll_s=poll_s)
                        return
                    seen = str(answer)
                finally:
                    page.close()
        if time.monotonic() >= deadline:
            raise PersonError(f"the sign-in window never showed the email field: {seen}")
        time.sleep(poll_s)


def _sign_in_tab(client: CdpClient) -> Page | None:
    """Return the tab on the sign-in page, attached, or `None`."""
    for target in client.pages():
        path = "/" + target.url.split("//", 1)[-1].partition("/")[2]
        if target.type == "page" and path.startswith(SIGN_IN_PATH):
            return client.attach(target.id)
    return None


def _await_link_sent(client: CdpClient, *, deadline: float, poll_s: float) -> None:
    while True:
        page = _sign_in_tab(client)
        if page is not None:
            try:
                if page.evaluate(LINK_SENT_JS) is True:
                    return
            finally:
                page.close()
        if time.monotonic() >= deadline:
            raise PersonError("the address went in, but the page never said the link was on its way")
        time.sleep(poll_s)


def newest_sign_in_link(host: str, port: int) -> str:
    """Return the newest sign-in link the mock minted: the message a person would read."""
    listed = running.witness_json(host, port, SIGN_IN_LINKS_JSON_PATH)
    if not listed:
        raise PersonError("the mock minted no sign-in link")
    return str(listed[-1]["link"])
