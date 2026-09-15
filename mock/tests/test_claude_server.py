"""The mock claude.ai's wire: cookies, redirects, and the pages a real browser would be given.

A real TLS connection to a real port, because that is what the mock is for. What
these cannot cover is a real Chrome running the page's own script — that is what
a rehearsal is.
"""

import base64
import io
import json
import urllib.error
import urllib.request
import zipfile
from urllib.parse import urlencode

from claudemock import server
from claudemock.site import Site
from mockcore import certificate

from conftest import EMAIL, WALL, Client, NoRedirect

SEED = "Part 1 of 1\n\nReply with exactly one line:\nMIGRATION-ACK aa000001 1/1\n"

LINK_SENT_CONTROLS = (
    (
        '<input data-testid="code" aria-label="Verification code" placeholder="Enter verification code" '
        'inputmode="numeric" autocomplete="one-time-code" id="code" name="code" type="text" value="">'
    ),
    '<button type="submit" data-testid="continue">Verify email address</button>',
    '<button type="button" id="resend">',
    '<button type="button" id="change">',
)
"""`link sent`, re-typed from `docs/spike/claude-sign-in-link-sent.html`."""


def ask_for_link(client: Client, *, email: str = EMAIL) -> str:
    """Submit the address as a browser does, and return the `Location` it was sent to."""
    client.request("/login")
    _, _, location = client.post("/login/email", urlencode({"email": email}).encode())
    return location


def newest_link(client: Client) -> tuple[str, str]:
    """Return the newest sign-in link's token and address, read off the fragment as the page does."""
    _, body, _ = client.request("/__mock/sign-in-links.json")
    listed = json.loads(body)
    assert listed, "no sign-in link was minted"
    fragment = listed[-1]["link"].split("#", 1)[1]
    token, address = fragment.split(":", 1)
    padded = address + "=" * (-len(address) % 4)
    return token, base64.urlsafe_b64decode(padded).decode("utf-8")


def sign_in(client: Client, *, email: str = EMAIL) -> str:
    """Return where a redeemed link sends the browser, walking the sign-in as a browser does.

    The address, the link read where the inbox would be, and the redeem post the
    landing page's script makes, with the pending-sign-in cookie the address step set.
    """
    ask_for_link(client, email=email)
    token, address = newest_link(client)
    _, body, _ = client.post("/login/redeem", urlencode({"token": token, "email": address}).encode())
    return str(json.loads(body)["next"])


def test_signed_out_every_page_is_the_login_page(running: Client) -> None:
    """`signed out`: the row the tool reads as an expired session."""
    for path in ("/", "/new", "/chat/anything", "/settings/data-privacy-controls"):
        status, _, location = running.request(path, follow=False)
        assert (status, location) == (303, "/login")


def test_the_login_page_hides_the_form_behind_the_banner(running: Client) -> None:
    _, body, _ = running.request("/login")
    assert 'id="cookie-banner"' in body
    assert '<main id="signin" hidden>' in body
    assert 'input type="email"' in body
    assert "Continue with Google" in body
    assert "Use a passkey" in body
    assert 'type="password"' not in body


def test_the_banner_is_dismissed_once(running: Client) -> None:
    running.cookies["mock_banner"] = "dismissed"
    _, body, _ = running.request("/login")
    assert 'id="cookie-banner"' not in body
    assert '<main id="signin">' in body


def test_the_address_step_mints_a_link_and_shows_the_link_sent_page(running: Client, site: Site) -> None:
    """`link requested`, then `link sent`: the real page's controls, and no password anywhere."""
    assert ask_for_link(running) == "/login"
    assert site.counters() == {**site.counters(), "links_minted": 1, "sign_ins": 0}
    _, body, _ = running.request("/login")
    for control in LINK_SENT_CONTROLS:
        assert control in body
    assert 'type="email"' not in body
    assert 'type="password"' not in body
    assert EMAIL in body


def test_the_link_is_listed_where_the_inbox_would_be(running: Client) -> None:
    ask_for_link(running)
    _, text, _ = running.request("/__mock/sign-in-links")
    lines = text.splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("https://claude.ai/magic-link#")
    token, address = newest_link(running)
    assert (len(token), address) == (32, EMAIL)
    _, body, _ = running.request("/__mock/sign-in-links.json")
    assert [item["spent"] for item in json.loads(body)] == [False]


def test_a_wrong_address_is_refused_and_the_form_says_so(running: Client) -> None:
    assert ask_for_link(running, email="someone@example.invalid") == "/login?error=refused"
    _, body, _ = running.request("/login?error=refused")
    assert 'role="alert"' in body
    assert 'type="email"' in body
    _, text, _ = running.request("/__mock/sign-in-links")
    assert not text


def test_the_link_signs_the_browser_that_asked_in(running: Client, site: Site) -> None:
    """`signed in by the link`: the redeem post answers with the session and where to go."""
    assert sign_in(running) == "/new"
    assert "mock_session" in running.cookies
    assert site.counters()["sign_ins"] == 1
    status, body, _ = running.request("/new")
    assert status == 200
    assert 'div contenteditable="true"' in body
    assert 'aria-label="Send message"' in body
    assert 'input type="file"' in body
    _, listed, _ = running.request("/__mock/sign-in-links.json")
    assert [item["spent"] for item in json.loads(listed)] == [True]


def test_a_spent_link_signs_nobody_in_again(running: Client, site: Site) -> None:
    sign_in(running)
    token, address = newest_link(running)
    other = Client(running.base)
    other.request("/login")
    _, body, _ = other.post("/login/redeem", urlencode({"token": token, "email": address}).encode())
    assert json.loads(body) == {"ok": False, "next": "/login"}
    assert site.counters()["sign_ins"] == 1


def test_a_link_opened_elsewhere_lands_that_browser_on_the_code_page(running: Client, site: Site) -> None:
    """`link opened elsewhere`: no pending sign-in here, so no session — and the page the tool recognises."""
    ask_for_link(running)
    token, address = newest_link(running)
    elsewhere = Client(running.base)
    _, body, _ = elsewhere.post("/login/redeem", urlencode({"token": token, "email": address}).encode())
    assert json.loads(body) == {"ok": False, "next": "/login"}
    assert "mock_session" not in elsewhere.cookies
    assert "mock_login" in elsewhere.cookies
    _, page, _ = elsewhere.request("/login")
    assert LINK_SENT_CONTROLS[0] in page
    assert site.counters()["sign_ins"] == 0
    # The browser that asked can still spend it.
    _, body, _ = running.post("/login/redeem", urlencode({"token": token, "email": address}).encode())
    assert json.loads(body)["next"] == "/new"


def test_the_landing_page_carries_the_script_that_spends_the_link(running: Client) -> None:
    """`sign-in link`: /magic-link needs no session, reads its own fragment and posts to /login/redeem."""
    status, body, _ = running.request("/magic-link", follow=False)
    assert status == 200
    assert "location.hash" in body
    assert "history.replaceState" in body
    assert "/login/redeem" in body
    assert "credentials: 'same-origin'" in body


def test_resend_and_change_address_do_what_their_buttons_say(running: Client, site: Site) -> None:
    ask_for_link(running)
    _, _, location = running.post("/login/resend", b"")
    assert location == "/login"
    assert site.counters()["links_minted"] == 2
    _, _, location = running.post("/login/change", b"")
    assert location == "/login"
    _, body, _ = running.request("/login")
    assert 'type="email"' in body
    assert LINK_SENT_CONTROLS[0] not in body


def test_a_code_is_never_accepted(running: Client) -> None:
    """§80: the code door is deferred, so the mock mints no code and takes none."""
    ask_for_link(running)
    _, _, location = running.post("/login/code", urlencode({"code": "123456"}).encode())
    assert location == "/login?error=code"
    _, body, _ = running.request("/login?error=code")
    assert 'role="alert"' in body
    assert LINK_SENT_CONTROLS[0] in body


def test_the_pending_sign_in_outlives_the_browser(running: Client) -> None:
    """The pending cookie has a lifetime, so `login --link` can reopen the profile (brief 07 §73)."""
    running.request("/login")
    _, _, _ = running.post("/login/email", urlencode({"email": EMAIL}).encode())
    request = urllib.request.Request(running.base + "/login/email", data=urlencode({"email": EMAIL}).encode())
    request.add_header("Cookie", f"mock_login={running.cookies['mock_login']}")
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=running.context), NoRedirect())
    try:
        opener.open(request, timeout=10)
    except urllib.error.HTTPError as answer:
        headers = answer.headers.get_all("Set-Cookie") or []
    assert any(header.startswith("mock_login=") and "Max-Age=3600" in header for header in headers), headers


def test_a_submit_makes_a_chat_that_survives_a_reload(running: Client, site: Site) -> None:
    sign_in(running)
    _, body, _ = running.post_json("/api/chats", {"text": SEED})
    chat_id = json.loads(body)["id"]

    status, page, _ = running.request(f"/chat/{chat_id}")
    assert status == 200
    assert 'data-testid="user-message"' in page
    assert "MIGRATION-ACK aa000001 1/1" in page  # the seed's own instruction line

    site.chat(chat_id).reply.started -= 10  # ty: ignore[possibly-unbound-attribute]
    _, page, _ = running.request(f"/chat/{chat_id}")
    assert 'data-testid="assistant-message"' in page
    assert 'aria-label="Send message"' in page
    assert site.counters()["chats_created"] == 1


def test_a_chat_that_is_not_there_is_not_found(running: Client) -> None:
    sign_in(running)
    status, _, _ = running.request("/chat/nope")
    assert status == 404


def test_a_second_message_goes_into_the_same_chat(running: Client, site: Site) -> None:
    sign_in(running)
    _, body, _ = running.post_json("/api/chats", {"text": SEED})
    chat_id = json.loads(body)["id"]
    site.chat(chat_id).reply.started -= 10  # ty: ignore[possibly-unbound-attribute]
    running.post_json(f"/api/chats/{chat_id}/messages", {"text": SEED})
    _, page, _ = running.request(f"/chat/{chat_id}")
    # The style block names the selector too, so the turns are counted as the
    # elements they are.
    assert page.count('<div data-testid="user-message">') == 2
    assert site.counters()["messages_received"] == 2


def test_a_rename_survives_a_reload(running: Client, site: Site) -> None:
    sign_in(running)
    _, body, _ = running.post_json("/api/chats", {"text": SEED})
    chat_id = json.loads(body)["id"]
    running.post_json(f"/api/chats/{chat_id}/title", {"title": "Notes on pooling"})
    _, page, _ = running.request(f"/chat/{chat_id}")
    assert '<button id="chat-menu-trigger" data-testid="chat-menu-trigger">Notes on ' in page
    assert "Notes on pooling</button>" in page
    assert site.counters()["renames"] == 1


def test_a_file_is_accepted_and_belongs_to_the_next_chat(running: Client, site: Site) -> None:
    sign_in(running)
    status, body, _ = running.post("/api/uploads", b"some bytes", **{"X-File-Name": "q3-chart.png"})
    assert (status, json.loads(body)["ok"]) == (200, True)
    _, chat, _ = running.post_json("/api/chats", {"text": SEED})
    _, page, _ = running.request(f"/chat/{json.loads(chat)['id']}")
    assert '<div class="attachment-chip">q3-chart.png</div>' in page
    assert site.counters()["files_accepted"] == 1


def test_an_upload_with_no_name_is_refused(running: Client) -> None:
    sign_in(running)
    status, _, _ = running.post("/api/uploads", b"some bytes")
    assert status == 400


def test_the_api_refuses_a_session_that_is_not_signed_in(running: Client) -> None:
    status, _, location = running.post_json("/api/chats", {"text": SEED})
    assert (status, location) == (303, "/login")


def test_the_ledger_is_served_as_a_block_and_as_json(running: Client) -> None:
    sign_in(running)
    _, block, _ = running.request("/__mock/ledger")
    assert block.startswith("Mock claude.ai — ledger\n\nSign-ins:")
    assert "Exports requested:" in block
    _, payload, _ = running.request("/__mock/ledger.json")
    assert json.loads(payload)["sign_ins"] == 1


# -- the export page (`32`) --------------------------------------------------- #


def test_the_export_page_has_the_button_the_dialog_and_the_status_hidden(running: Client) -> None:
    """`export page`, `export button`, `export confirmation`, `export requested`, at rest."""
    sign_in(running)
    status, page, _ = running.request("/settings/data-privacy-controls")
    assert status == 200
    decoy = page.index('<button class="invisible" data-testid="export-data">')
    assert decoy < page.index('<button data-testid="export-data">Export data</button>')
    assert '<div role="dialog" aria-label="Export data" hidden>' in page
    assert '<button type="submit" data-testid="confirm-export">' in page
    assert '<div role="status" data-testid="export-requested" hidden>' in page
    assert "<div contenteditable" not in page


def test_an_export_ask_is_counted_and_answers_with_a_link(running: Client, site: Site) -> None:
    sign_in(running)
    status, body, _ = running.post_json("/api/exports", {})
    payload = json.loads(body)
    assert (status, payload["ok"]) == (200, True)
    assert payload["link"].startswith(running.base + "/__mock/exports/")
    assert payload["link"].endswith(".zip")
    assert site.counters()["exports_requested"] == 1


def test_an_export_ask_needs_a_session(running: Client, site: Site) -> None:
    status, _, location = running.post_json("/api/exports", {})
    assert (status, location) == (303, "/login")
    assert site.counters()["exports_requested"] == 0


def test_the_link_serves_the_chats_as_an_export(running: Client, site: Site) -> None:
    """The archive is the vendor's shape, rendered from the chats at the moment of the fetch."""
    sign_in(running)
    _, body, _ = running.post_json("/api/chats", {"text": SEED})
    chat_id = json.loads(body)["id"]
    site.chat(chat_id).reply.started -= 10  # ty: ignore[possibly-unbound-attribute]
    running.post_json(f"/api/chats/{chat_id}/title", {"title": "Notes on pooling"})
    _, asked, _ = running.post_json("/api/exports", {})
    path = json.loads(asked)["link"].removeprefix(running.base)

    status, payload = running.get_bytes(path)
    assert status == 200
    assert zipfile.is_zipfile(io.BytesIO(payload))
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert sorted(archive.namelist()) == ["conversations.json", "users.json"]
        conversations = json.loads(archive.read("conversations.json"))
    assert [conversation["uuid"] for conversation in conversations] == [chat_id]
    assert conversations[0]["name"] == "Notes on pooling"
    assert [turn["sender"] for turn in conversations[0]["chat_messages"]] == ["human", "assistant"]
    assert conversations[0]["chat_messages"][1]["text"] == "MIGRATION-ACK aa000001 1/1"


def test_a_link_nobody_asked_for_is_not_found(running: Client) -> None:
    """What the tool reports as `link refused: HTTP 404`, and leaves the ask open on."""
    status, _ = running.get_bytes("/__mock/exports/deadbeef.zip")
    assert status == 404


def test_the_open_links_are_listed_as_text_and_as_json(running: Client) -> None:
    sign_in(running)
    _, before, _ = running.request("/__mock/exports")
    assert not before
    _, first, _ = running.post_json("/api/exports", {})
    _, second, _ = running.post_json("/api/exports", {})
    links = [json.loads(first)["link"], json.loads(second)["link"]]

    _, text, _ = running.request("/__mock/exports")
    assert text == "".join(f"{link}\n" for link in links)
    running.get_bytes(links[0].removeprefix(running.base))
    _, payload, _ = running.request("/__mock/exports.json")
    listed = json.loads(payload)
    assert [entry["link"] for entry in listed] == links
    assert [entry["fetched"] for entry in listed] == [1, 0]
    assert [entry["requested_at"] for entry in listed] == [WALL, WALL]
    assert all(entry["token"] in entry["link"] for entry in listed)


def test_a_link_is_announced_as_it_is_minted(site: Site, material: certificate.Material) -> None:
    """The mock has no inbox: the link goes to whoever `serve` was told to tell — sign-in links too (`49`)."""
    announced: list[str] = []
    sign_ins: list[str] = []
    started = server.serve(site, port=0, material=material, announce=announced.append, announce_sign_in=sign_ins.append)
    try:
        client = Client(f"https://127.0.0.1:{started.port}")
        sign_in(client)
        _, body, _ = client.post_json("/api/exports", {})
    finally:
        started.close()
    assert announced == [json.loads(body)["link"]]
    assert sign_ins == [site.link_of(site.sign_in_links()[0])]
