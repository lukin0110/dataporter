"""The wire: cookies, redirects, and the pages a real browser would be given.

A real TLS connection to a real port, because that is what the mock is for. What
these cannot cover is a real Chrome running the page's own script — that is what
a rehearsal is.
"""

import json
from urllib.parse import urlencode

from claudemock.site import Site

from conftest import EMAIL, PASSWORD, Client

SEED = "Part 1 of 1\n\nReply with exactly one line:\nMIGRATION-ACK aa000001 1/1\n"


def sign_in(client: Client, *, email: str = EMAIL, password: str = PASSWORD) -> str:
    """The two steps, as a browser walks them. Returns the last `Location`."""
    client.request("/login")
    client.post("/login/email", urlencode({"email": email}).encode())
    client.request("/login")
    _, _, location = client.post(
        "/login/password", urlencode({"password": password}).encode()
    )
    return location


def test_signed_out_every_page_is_the_login_page(running: Client) -> None:
    """`signed out`: the row the tool reads as an expired session."""
    for path in ("/", "/new", "/chat/anything"):
        status, _, location = running.request(path, follow=False)
        assert (status, location) == (303, "/login")


def test_the_login_page_hides_the_form_behind_the_banner(running: Client) -> None:
    _, body, _ = running.request("/login")
    assert 'id="cookie-banner"' in body
    assert '<main id="signin" hidden>' in body
    assert 'input type="email"' in body
    assert "Continue with Google" in body
    assert "Use a passkey" in body


def test_the_banner_is_dismissed_once(running: Client) -> None:
    running.cookies["mock_banner"] = "dismissed"
    _, body, _ = running.request("/login")
    assert 'id="cookie-banner"' not in body
    assert '<main id="signin">' in body


def test_the_email_step_becomes_the_password_step(running: Client) -> None:
    running.request("/login")
    status, _, location = running.post(
        "/login/email", urlencode({"email": EMAIL}).encode()
    )
    assert (status, location) == (303, "/login")
    _, body, _ = running.request("/login")
    assert 'type="password"' in body
    assert 'type="email"' not in body


def test_a_wrong_email_is_refused_and_the_form_says_so(running: Client) -> None:
    running.request("/login")
    _, _, location = running.post(
        "/login/email", urlencode({"email": "someone@example.invalid"}).encode()
    )
    assert location == "/login?error=refused"
    _, body, _ = running.request("/login?error=refused")
    assert 'role="alert"' in body
    assert 'type="email"' in body


def test_a_wrong_password_is_refused(running: Client, site: Site) -> None:
    assert sign_in(running, password="guess") == "/login?error=refused"
    assert site.counters()["sign_ins"] == 0


def test_the_configured_pair_signs_in(running: Client, site: Site) -> None:
    assert sign_in(running) == "/new"
    assert site.counters()["sign_ins"] == 1
    status, body, _ = running.request("/new")
    assert status == 200
    assert 'div contenteditable="true"' in body
    assert 'aria-label="Send message"' in body
    assert 'input type="file"' in body


def test_a_submit_makes_a_chat_that_survives_a_reload(
    running: Client, site: Site
) -> None:
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
    assert '<button id="chat-menu-trigger" data-testid="chat-menu-trigger">Notes on '
    assert "Notes on pooling</button>" in page
    assert site.counters()["renames"] == 1


def test_a_file_is_accepted_and_belongs_to_the_next_chat(
    running: Client, site: Site
) -> None:
    sign_in(running)
    status, body, _ = running.post(
        "/api/uploads", b"some bytes", **{"X-File-Name": "q3-chart.png"}
    )
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
    _, payload, _ = running.request("/__mock/ledger.json")
    assert json.loads(payload)["sign_ins"] == 1
