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
from mockcore import wire

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


def test_signed_out_every_page_goes_to_the_login_page_by_way_of_logout(running: Client) -> None:
    """`signed out` and `involuntary sign-out`: the two hops a real account takes.

    `/settings/data-privacy-controls` is in the list because it is *not* a page
    here any more — `51` found it serves nothing on claude.ai — so it falls to the
    catch-all and takes the same two hops as anything else nobody asked for.
    """
    for path in ("/", "/new", "/chat/anything", "/settings/data-privacy-controls"):
        status, _, location = running.request(path, follow=False)
        assert (status, location) == (303, f"/logout?involuntary=1&returnTo={path}")
    status, _, location = running.request("/logout?involuntary=1&returnTo=/new", follow=False)
    assert (status, location) == (303, "/login?from=logout&reauth=1&returnTo=/new")


def test_a_session_the_site_has_forgotten_is_an_involuntary_logout(running: Client, site: Site) -> None:
    """`involuntary sign-out`: a sign-in that lapses in the middle of a run.

    The browser keeps its cookie and the site stops knowing the token, which is
    what makes this different from never having signed in — and identical from
    the outside, which is the point.
    """
    sign_in(running)
    status, _, _ = running.request("/new", follow=False)
    assert status == 200
    status, payload, _ = running.post_json("/__mock/expire-session", {})
    assert (status, json.loads(payload)) == (200, {"expired": 1})
    assert running.cookies.get("mock_session")
    status, _, location = running.request("/new", follow=False)
    assert (status, location) == (303, "/logout?involuntary=1&returnTo=/new")


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
    assert lines[0].startswith(f"{running.base}/magic-link#")
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
    opener = urllib.request.build_opener(NoRedirect())
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
    assert (status, location) == (303, "/logout?involuntary=1&returnTo=/api/chats")


def test_the_ledger_is_served_as_a_block_and_as_json(running: Client) -> None:
    sign_in(running)
    _, block, _ = running.request("/__mock/ledger")
    assert block.startswith("Mock claude.ai — ledger\n\nSign-ins:")
    assert "Exports requested:" in block
    _, payload, _ = running.request("/__mock/ledger.json")
    assert json.loads(payload)["sign_ins"] == 1


# -- the settings panel and the export (`32`, `51`) --------------------------- #


def path_of(link: str, client: "Client") -> str:
    """Return the path of a link the mock minted, which is spelled with its own address.

    The address the socket really bound (`65`), not a name: there is no resolver
    rule any more, so a link is where the browser can actually reach it — which
    under the tests is an ephemeral port.
    """
    assert link.startswith(client.base), (link, client.base)
    return link.removeprefix(client.base)


def ask_for_an_export(client: Client) -> tuple[int, dict[str, object]]:
    status, body, _ = client.post_json("/api/exports", {})
    return status, json.loads(body)


def fetch(client: Client, path: str) -> tuple[int, bytes]:
    """Take a link the way the tool now does: in the browser, carrying its session."""
    return client.get_bytes(path, cookies=True)


def test_the_settings_panel_is_markup_on_the_app_and_not_a_page(running: Client) -> None:
    """`export page`: claude.ai asks for an export from a dialog at a fragment of `/new`.

    A fragment never reaches a server, so the panel ships with the chat page and
    the page's own script opens it on the address. The path `31` guessed is not
    served at all — signed in, it is not found, which is what the real one does.
    """
    sign_in(running)
    status, page, _ = running.request("/new")
    assert status == 200
    assert '<div data-perf-screen="data-privacy-controls" role="dialog" aria-label="Settings" hidden></div>' in page
    assert "#settings/data-privacy-controls" in page
    assert "<div contenteditable" in page  # the app is behind it, as on the real panel
    status, _, _ = running.request("/settings/data-privacy-controls", follow=False)
    assert status == 404


def test_the_panel_offers_six_buttons_of_which_the_export_row_is_the_first_visible(running: Client) -> None:
    """`export button`: matched by position, so the position has to be worth matching."""
    sign_in(running)
    _, page, _ = running.request("/new")
    root = page[page.index('<template id="settings-root">') : page.index("</template>")]
    assert root.count('button data-cds="Button"') == 6  # the count a sketch of the real panel took
    assert root.count('role="switch"') == 1
    visible_export = root.index("<div data-settings-row>\n    <span>Export data</span>")
    # First the row that is there and not shown, then a row holding a switch and
    # no button at all, and only then the Export row: so the first match of the
    # tool's selector is invisible and the first *visible* match is the right one.
    assert root.index('data-settings-row class="invisible"') < root.index('role="switch"') < visible_export
    assert root.index('button data-cds="Button"') < root.index('role="switch"')
    assert visible_export < root.index("<span>Manage memories</span>")


def test_the_second_screen_carries_the_confirmation_and_the_period(running: Client) -> None:
    """`export confirmation` and `export period`: a screen of its own, at an address of its own."""
    sign_in(running)
    _, page, _ = running.request("/new")
    screen = page[page.index('<template id="settings-export">') :]
    assert '<button type="button" data-testid="export-confirm-button">Export</button>' in screen
    assert '<div role="radiogroup" aria-label="Conversations from">' in screen
    assert 'value="All" checked' in screen
    assert "#settings/data-privacy-controls/export-data" in page


def test_an_export_ask_is_accepted_and_answers_with_a_link(running: Client, site: Site) -> None:
    """202, because the real one answers accepted rather than done."""
    sign_in(running)
    status, payload = ask_for_an_export(running)
    assert (status, payload["ok"]) == (202, True)
    link = str(payload["link"])
    assert link.startswith(running.base + "/__mock/exports/")
    assert not link.endswith(".zip")  # the index, not one of the zips it names
    assert site.counters()["exports_requested"] == 1


def test_an_export_ask_needs_a_session(running: Client, site: Site) -> None:
    status, _, location = running.post_json("/api/exports", {})
    assert (status, location) == (303, "/logout?involuntary=1&returnTo=/api/exports")
    assert site.counters()["exports_requested"] == 0


def test_the_link_serves_a_manifest_naming_a_part_per_category(running: Client, site: Site) -> None:
    """What `adb0494` taught the tool: a Claude export is an index and its parts."""
    sign_in(running)
    _, body, _ = running.post_json("/api/chats", {"text": SEED})
    chat_id = json.loads(body)["id"]
    site.chat(chat_id).reply.started -= 10  # ty: ignore[possibly-unbound-attribute]
    running.post_json(f"/api/chats/{chat_id}/title", {"title": "Notes on pooling"})
    _, payload = ask_for_an_export(running)

    status, index = fetch(running, path_of(str(payload["link"]), running))
    assert status == 200
    manifest = json.loads(index)
    assert manifest["total_files"] == 2
    assert [each["filename"] for each in manifest["data_files"]] == [
        "light_metadata-000.zip",
        "conversations-000.zip",
    ]

    members = {}
    for each in manifest["data_files"]:
        status, part = fetch(running, path_of(each["export_url"], running))
        assert status == 200
        with zipfile.ZipFile(io.BytesIO(part)) as opened:
            members[each["category"]] = sorted(opened.namelist())
            if each["category"] == "conversations":
                conversations = json.loads(opened.read("conversations.json"))
    assert members == {"light_metadata": ["users.json"], "conversations": ["conversations.json"]}
    assert [conversation["uuid"] for conversation in conversations] == [chat_id]
    assert conversations[0]["name"] == "Notes on pooling"
    assert [turn["sender"] for turn in conversations[0]["chat_messages"]] == ["human", "assistant"]
    assert conversations[0]["chat_messages"][1]["text"] == "MIGRATION-ACK aa000001 1/1"


def test_a_parts_address_carries_nothing_of_the_links_own_token(running: Client) -> None:
    """The tool files the manifest, so whatever is in a part's URL is on disk.

    A real manifest hangs its files under the account's uuid — the same one in
    every export — and gives each a hex token of its own, so the link an operator
    pasted survives nowhere. `the link is in no file the run left` is the
    rehearsal criterion that says so, and this is the same claim at the unit.
    """
    sign_in(running)
    _, payload = ask_for_an_export(running)
    link = str(payload["link"])
    token = link.rsplit("/", 1)[-1]
    _, index = fetch(running, path_of(link, running))
    urls = [each["export_url"] for each in json.loads(index)["data_files"]]
    assert urls
    assert all(token not in url for url in urls)
    assert all(url.startswith(running.base + "/__mock/export/") for url in urls)


def test_a_part_may_be_fetched_once_and_the_index_as_often_as_you_like(running: Client) -> None:
    """The manifest's own words about its own files: each URL can only be used once."""
    sign_in(running)
    _, payload = ask_for_an_export(running)
    link = path_of(str(payload["link"]), running)
    status, index = fetch(running, link)
    assert status == 200
    assert fetch(running, link)[0] == 200  # the index may be read again

    part = path_of(json.loads(index)["data_files"][0]["export_url"], running)
    assert fetch(running, part)[0] == 200
    assert fetch(running, part)[0] == 404


def test_an_export_is_fetched_through_the_session(running: Client) -> None:
    """`f9e0310`: a real link answered 403 to a request without the session."""
    sign_in(running)
    _, payload = ask_for_an_export(running)
    link = path_of(str(payload["link"]), running)
    _, index = fetch(running, link)
    part = path_of(json.loads(index)["data_files"][0]["export_url"], running)

    signed_out = Client(running.base)
    assert signed_out.request(link, follow=False)[0] == 303
    assert signed_out.request(part, follow=False)[0] == 303
    assert fetch(running, part)[0] == 200  # and the part was not spent by the refusal


def test_a_link_nobody_asked_for_is_not_found(running: Client) -> None:
    """What the tool reports as `link refused: HTTP 404`, and leaves the ask open on."""
    sign_in(running)
    assert fetch(running, "/__mock/exports/deadbeef")[0] == 404
    assert fetch(running, "/__mock/export/deadbeef/download/f00d.zip")[0] == 404


def test_the_open_links_are_listed_as_text_and_as_json(running: Client) -> None:
    sign_in(running)
    _, before, _ = running.request("/__mock/exports")
    assert not before
    _, first, _ = running.post_json("/api/exports", {})
    _, second, _ = running.post_json("/api/exports", {})
    links = [json.loads(first)["link"], json.loads(second)["link"]]

    _, text, _ = running.request("/__mock/exports")
    assert text == "".join(f"{link}\n" for link in links)
    fetch(running, path_of(links[0], running))
    _, payload, _ = running.request("/__mock/exports.json")
    listed = json.loads(payload)
    assert [entry["link"] for entry in listed] == links
    assert [entry["fetched"] for entry in listed] == [1, 0]
    assert [entry["requested_at"] for entry in listed] == [WALL, WALL]
    assert all(entry["token"] in entry["link"] for entry in listed)


def test_a_link_is_announced_as_it_is_minted(site: Site) -> None:
    """The mock has no inbox: the link goes to whoever `serve` was told to tell — sign-in links too (`49`)."""
    announced: list[str] = []
    sign_ins: list[str] = []
    started = server.serve(site, port=0, announce=announced.append, announce_sign_in=sign_ins.append)
    try:
        client = Client(wire.origin_of("127.0.0.1", started.port))
        sign_in(client)
        _, body, _ = client.post_json("/api/exports", {})
    finally:
        started.close()
    assert announced == [json.loads(body)["link"]]
    assert sign_ins == [site.link_of(site.sign_in_links()[0])]
