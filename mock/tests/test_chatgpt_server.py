"""The mock chatgpt.com's wire: two hosts, one application, and the pages a browser would be given.

A real TLS connection to a real port. The crossing between hosts is asserted as
the `Location` a browser would be sent to, and then walked by path: the test
client has no resolver rule, and the mock's routes are paths alone.
"""

import io
import json
import zipfile
from urllib.parse import urlencode

from chatgptmock.site import Site

from conftest import EMAIL, PASSWORD, WALL, Client

SEED = "Part 1 of 1\n\nReply with exactly one line:\nMIGRATION-ACK aa000001 1/1\n"

AUTH = "https://auth.openai.com"
SITE = "https://chatgpt.com"


def sign_in(client: Client, *, email: str = EMAIL, password: str = PASSWORD) -> str:
    """Return the last `Location`, walking the steps as a browser does: the auth host, then the callback."""
    client.request("/log-in")
    client.post("/log-in/email", urlencode({"email": email}).encode())
    client.request("/log-in")
    _, _, location = client.post("/log-in/password", urlencode({"password": password}).encode())
    if not location.startswith(SITE):
        return location
    _, _, location = client.request(location.removeprefix(SITE), follow=False)
    return location


# -- signed out, and the sign-in on two hosts ---------------------------------- #


def test_signed_out_the_root_is_the_landing_page(chatgpt_running: Client) -> None:
    """`signed out`: a Log in control and a Sign up control at the site root."""
    status, body, _ = chatgpt_running.request("/")
    assert status == 200
    assert (
        '<button type="button" data-testid="login-button" onclick="location.href=\'https://auth.openai.com/log-in\'">Log in</button>'
        in body
    )
    assert "Sign up" in body
    assert "contenteditable" not in body


def test_signed_out_every_other_path_redirects_to_the_root(chatgpt_running: Client) -> None:
    for path in ("/c/anything", "/settings", "/settings/data-controls", "/api/chats/x", "/anything"):
        status, _, location = chatgpt_running.request(path, follow=False)
        assert (status, location) == (303, "/"), path


def test_the_login_page_on_the_site_host_sends_the_browser_to_the_auth_host(chatgpt_running: Client) -> None:
    """`auth host`: the sign-in passes through auth.openai.com."""
    status, _, location = chatgpt_running.request("/auth/login", follow=False)
    assert (status, location) == (303, f"{AUTH}/log-in")


def test_the_email_step_has_a_continue_and_the_providers(chatgpt_running: Client) -> None:
    """`email step`, `other providers`, `cookie banner`: a field, Continue, three buttons, no banner."""
    _, body, _ = chatgpt_running.request("/log-in")
    assert 'input type="email"' in body
    assert '<button type="submit">Continue</button>' in body
    for provider in ("Google", "Microsoft", "Apple"):
        assert f"Continue with {provider}" in body
    assert "banner" not in body
    assert 'type="password"' not in body


def test_the_providers_lead_nowhere_useful(chatgpt_running: Client) -> None:
    status, body, _ = chatgpt_running.request("/log-in/unsupported")
    assert status == 200
    assert "<form" not in body
    assert "email address and a password" in body


def test_the_email_step_becomes_the_password_step(chatgpt_running: Client) -> None:
    chatgpt_running.request("/log-in")
    status, _, location = chatgpt_running.post("/log-in/email", urlencode({"email": EMAIL}).encode())
    assert (status, location) == (303, "/log-in")
    _, body, _ = chatgpt_running.request("/log-in")
    assert 'input type="password"' in body
    assert '<button type="submit">Continue</button>' in body
    assert 'type="email"' not in body


def test_a_wrong_email_is_refused_and_the_form_says_so(chatgpt_running: Client) -> None:
    chatgpt_running.request("/log-in")
    _, _, location = chatgpt_running.post("/log-in/email", urlencode({"email": "someone@example.invalid"}).encode())
    assert location == "/log-in?error=refused"
    _, body, _ = chatgpt_running.request("/log-in?error=refused")
    assert 'role="alert"' in body
    assert 'type="email"' in body


def test_a_wrong_password_is_refused_back_to_the_email_step(chatgpt_running: Client, chatgpt_site: Site) -> None:
    """`password step`: a wrong pair is refused back to the email step."""
    assert sign_in(chatgpt_running, password="guess") == "/log-in?error=refused"
    _, body, _ = chatgpt_running.request("/log-in?error=refused")
    assert 'type="email"' in body
    assert 'role="alert"' in body
    assert chatgpt_site.counters()["sign_ins"] == 0


def test_the_right_pair_comes_back_to_the_site_host_with_a_code(chatgpt_running: Client) -> None:
    chatgpt_running.request("/log-in")
    chatgpt_running.post("/log-in/email", urlencode({"email": EMAIL}).encode())
    _, _, location = chatgpt_running.post("/log-in/password", urlencode({"password": PASSWORD}).encode())
    assert location.startswith(f"{SITE}/auth/callback?code=")
    assert len(location.removeprefix(f"{SITE}/auth/callback?code=")) == 16


def test_the_callback_turns_the_code_into_a_session_once(chatgpt_running: Client, chatgpt_site: Site) -> None:
    """`auth host`: the code is one-time, and the session is the site host's cookie."""
    assert sign_in(chatgpt_running) == "/"
    assert chatgpt_site.counters()["sign_ins"] == 1
    assert "mock_session" in chatgpt_running.cookies
    status, body, _ = chatgpt_running.request("/")
    assert status == 200
    assert 'id="prompt-textarea" contenteditable="true"' in body


def test_a_code_nobody_minted_is_refused_to_the_auth_host(chatgpt_running: Client, chatgpt_site: Site) -> None:
    status, _, location = chatgpt_running.request("/auth/callback?code=deadbeef", follow=False)
    assert (status, location) == (303, f"{AUTH}/log-in?error=refused")
    assert chatgpt_site.counters()["sign_ins"] == 0


def test_a_code_is_spent_by_its_first_use(chatgpt_running: Client, chatgpt_site: Site) -> None:
    chatgpt_running.request("/log-in")
    chatgpt_running.post("/log-in/email", urlencode({"email": EMAIL}).encode())
    _, _, location = chatgpt_running.post("/log-in/password", urlencode({"password": PASSWORD}).encode())
    path = location.removeprefix(SITE)
    chatgpt_running.request(path, follow=False)
    again = Client(chatgpt_running.base)
    status, _, location = again.request(path, follow=False)
    assert (status, location) == (303, f"{AUTH}/log-in?error=refused")
    assert chatgpt_site.counters()["sign_ins"] == 1


# -- the chats ---------------------------------------------------------------- #


def test_the_new_chat_page_has_the_composer_the_controls_and_the_sidebar(chatgpt_running: Client) -> None:
    """`new chat`, `composer present`, `can submit`, `upload target`, `settings`."""
    sign_in(chatgpt_running)
    _, body, _ = chatgpt_running.request("/")
    assert '<a data-testid="create-new-chat-button" href="/">New chat</a>' in body
    assert '<div id="prompt-textarea" contenteditable="true" role="textbox"' in body
    assert 'id="composer-submit-button" data-testid="send-button" aria-label="Send prompt" disabled' in body
    assert 'data-testid="composer-plus-btn" aria-label="Add files and more"' in body
    assert '<input type="file" multiple style="display: none">' in body
    assert 'data-testid="profile-button"' in body
    assert '<a role="menuitem" href="/settings">Settings</a>' in body
    assert "const THRESHOLD = 10000;" in body


def test_a_submit_makes_a_chat_at_its_own_url_that_survives_a_reload(
    chatgpt_running: Client, chatgpt_site: Site
) -> None:
    """`conversation`, `human turn`, `assistant turn`, `generating`, `generation finished`."""
    sign_in(chatgpt_running)
    _, body, _ = chatgpt_running.post_json("/api/chats", {"text": SEED})
    chat = json.loads(body)
    assert chat["generating"] is True
    assert [turn["role"] for turn in chat["turns"]] == ["user"]

    status, page, _ = chatgpt_running.request(f"/c/{chat['id']}")
    assert status == 200
    assert '<div data-message-author-role="user">' in page
    assert '<div class="whitespace-pre-wrap">Part 1 of 1' in page
    assert 'data-testid="stop-button" aria-label="Stop streaming"' in page
    assert 'data-testid="copy-turn-action-button"' not in page

    chatgpt_site.chat(chat["id"]).reply.started -= 10  # ty: ignore[possibly-unbound-attribute]
    _, page, _ = chatgpt_running.request(f"/c/{chat['id']}")
    assert '<div data-message-author-role="assistant">' in page
    assert '<div class="markdown">MIGRATION-ACK aa000001 1/1</div>' in page
    assert 'data-testid="copy-turn-action-button" aria-label="Copy response"' in page
    assert 'data-testid="send-button" aria-label="Send prompt"' in page
    assert f'<a href="/c/{chat["id"]}" aria-label="New chat">New chat</a>' in page
    assert 'data-testid="history-item-0-options"' in page
    assert chatgpt_site.counters()["chats_created"] == 1


def test_a_chat_that_is_not_there_is_not_found(chatgpt_running: Client) -> None:
    sign_in(chatgpt_running)
    assert chatgpt_running.request("/c/nope")[0] == 404
    assert chatgpt_running.request("/api/chats/nope")[0] == 404
    assert chatgpt_running.post_json("/api/chats/nope/messages", {"text": "x"})[0] == 404
    assert chatgpt_running.post_json("/api/chats/nope/title", {"title": "x"})[0] == 404
    assert chatgpt_running.post("/api/chats/nope/stop", b"")[0] == 404


def test_a_pasted_text_reaches_the_site_apart_from_the_typed_text(chatgpt_running: Client, chatgpt_site: Site) -> None:
    """`paste over the threshold`: the page sends the chip's text apart, and the reply reads it."""
    sign_in(chatgpt_running)
    _, body, _ = chatgpt_running.post_json("/api/chats", {"text": "here it is", "pasted": [SEED]})
    chat = json.loads(body)
    assert chat["turns"][0] == {"role": "user", "text": "here it is", "pasted": [SEED], "files": []}
    chatgpt_site.chat(chat["id"]).reply.started -= 10  # ty: ignore[possibly-unbound-attribute]
    _, page, _ = chatgpt_running.request(f"/c/{chat['id']}")
    assert (
        '<div class="attachment-chip" data-testid="pasted-text-attachment">Pasted text<div class="whitespace-pre-wrap">Part 1 of 1'
        in page
    )
    assert '<div class="markdown">MIGRATION-ACK aa000001 1/1</div>' in page


def test_a_second_message_goes_into_the_same_chat(chatgpt_running: Client, chatgpt_site: Site) -> None:
    sign_in(chatgpt_running)
    _, body, _ = chatgpt_running.post_json("/api/chats", {"text": SEED})
    chat_id = json.loads(body)["id"]
    chatgpt_site.chat(chat_id).reply.started -= 10  # ty: ignore[possibly-unbound-attribute]
    _, body, _ = chatgpt_running.post_json(f"/api/chats/{chat_id}/messages", {"text": SEED})
    assert [turn["role"] for turn in json.loads(body)["turns"]] == ["user", "assistant", "user"]
    _, page, _ = chatgpt_running.request(f"/c/{chat_id}")
    assert page.count('<div data-message-author-role="user">') == 2
    assert chatgpt_site.counters()["messages_received"] == 2


def test_the_stop_control_stops_the_reply(chatgpt_running: Client, chatgpt_site: Site) -> None:
    sign_in(chatgpt_running)
    _, body, _ = chatgpt_running.post_json("/api/chats", {"text": SEED})
    chat_id = json.loads(body)["id"]
    status, body, _ = chatgpt_running.post(f"/api/chats/{chat_id}/stop", b"")
    assert status == 200
    assert json.loads(body)["generating"] is False
    assert not chatgpt_site.chat(chat_id).generating(chatgpt_site.now())  # ty: ignore[possibly-unbound-attribute]


def test_a_rename_survives_a_reload_in_the_sidebar_and_the_title(chatgpt_running: Client, chatgpt_site: Site) -> None:
    """`rename affordance`, `chat title`: the entry's aria-label and the document title."""
    sign_in(chatgpt_running)
    _, body, _ = chatgpt_running.post_json("/api/chats", {"text": SEED})
    chat_id = json.loads(body)["id"]
    chatgpt_running.post_json(f"/api/chats/{chat_id}/title", {"title": "Notes on pooling"})
    _, page, _ = chatgpt_running.request(f"/c/{chat_id}")
    assert f'<a href="/c/{chat_id}" aria-label="Notes on pooling">Notes on pooling</a>' in page
    assert "<title>Notes on pooling</title>" in page
    assert '<div role="menuitem" data-action="rename">Rename</div>' in page
    assert '<input type="text" aria-label="Chat title" hidden>' in page
    assert chatgpt_site.counters()["renames"] == 1


def test_the_sidebar_numbers_entries_newest_first(chatgpt_running: Client) -> None:
    sign_in(chatgpt_running)
    _, first, _ = chatgpt_running.post_json("/api/chats", {"text": SEED})
    _, second, _ = chatgpt_running.post_json("/api/chats", {"text": SEED})
    _, page, _ = chatgpt_running.request("/")
    newest = page.index(f'data-chat-id="{json.loads(second)["id"]}"')
    oldest = page.index(f'data-chat-id="{json.loads(first)["id"]}"')
    assert newest < oldest
    assert page.index("history-item-0-options") < page.index("history-item-1-options")


def test_a_file_is_accepted_and_belongs_to_the_next_message(chatgpt_running: Client, chatgpt_site: Site) -> None:
    """`upload accepted`: shown by name, on the message that carried it."""
    sign_in(chatgpt_running)
    status, body, _ = chatgpt_running.post("/api/uploads", b"some bytes", **{"X-File-Name": "q3-chart.png"})
    assert (status, json.loads(body)) == (200, {"ok": True, "file_name": "q3-chart.png", "bytes": 10})
    _, chat, _ = chatgpt_running.post_json("/api/chats", {"text": SEED})
    assert json.loads(chat)["turns"][0]["files"] == ["q3-chart.png"]
    _, page, _ = chatgpt_running.request(f"/c/{json.loads(chat)['id']}")
    assert '<div class="attachment-chip">q3-chart.png</div>' in page
    assert chatgpt_site.counters()["files_accepted"] == 1


def test_an_upload_with_no_name_is_refused(chatgpt_running: Client) -> None:
    sign_in(chatgpt_running)
    assert chatgpt_running.post("/api/uploads", b"some bytes")[0] == 400


def test_the_api_refuses_a_session_that_is_not_signed_in(chatgpt_running: Client) -> None:
    status, _, location = chatgpt_running.post_json("/api/chats", {"text": SEED})
    assert (status, location) == (303, "/")


def test_the_ledger_is_served_as_a_block_and_as_json(chatgpt_running: Client) -> None:
    sign_in(chatgpt_running)
    _, block, _ = chatgpt_running.request("/__mock/ledger")
    assert block.startswith("Mock chatgpt.com — ledger\n\nSign-ins:                      1\n")
    _, payload, _ = chatgpt_running.request("/__mock/ledger.json")
    assert json.loads(payload)["sign_ins"] == 1


# -- settings, the export page and the archive --------------------------------- #


def test_settings_lists_data_controls(chatgpt_running: Client) -> None:
    sign_in(chatgpt_running)
    status, body, _ = chatgpt_running.request("/settings")
    assert status == 200
    assert '<a href="/settings/data-controls">Data controls</a>' in body


def test_the_export_page_has_the_control_the_dialog_and_the_status_hidden(chatgpt_running: Client) -> None:
    """`export page`, `export button`, `export confirmation`, `export requested`, at rest."""
    sign_in(chatgpt_running)
    status, page, _ = chatgpt_running.request("/settings/data-controls")
    assert status == 200
    assert "Improve the model for everyone" in page
    assert "<h2>Export data</h2>" in page
    assert '<button type="button" id="export">Export</button>' in page
    assert '<div role="dialog" aria-label="Request data export" hidden>' in page
    assert '<button type="button" id="confirm-export">Confirm export</button>' in page
    assert '<div role="status" id="export-requested" hidden>' in page
    assert "contenteditable" not in page
    assert 'type="file"' not in page


def test_an_export_ask_is_counted_and_answers_with_a_link_on_the_site_host(
    chatgpt_running: Client, chatgpt_site: Site
) -> None:
    sign_in(chatgpt_running)
    status, body, _ = chatgpt_running.post_json("/api/exports", {})
    payload = json.loads(body)
    assert (status, payload["ok"]) == (200, True)
    assert payload["link"].startswith("https://chatgpt.com/__mock/exports/")
    assert payload["link"].endswith(".zip")
    assert chatgpt_site.counters()["exports_requested"] == 1


def test_an_export_ask_needs_a_session(chatgpt_running: Client, chatgpt_site: Site) -> None:
    status, _, location = chatgpt_running.post_json("/api/exports", {})
    assert (status, location) == (303, "/")
    assert chatgpt_site.counters()["exports_requested"] == 0


def test_the_download_wants_a_session(chatgpt_running: Client, chatgpt_site: Site) -> None:
    """`download needs session`: served to the signed-in session, refused to anyone else, the listing open."""
    sign_in(chatgpt_running)
    _, body, _ = chatgpt_running.post_json("/api/chats", {"text": SEED})
    chat_id = json.loads(body)["id"]
    chatgpt_site.chat(chat_id).reply.started -= 10  # ty: ignore[possibly-unbound-attribute]
    chatgpt_running.post_json(f"/api/chats/{chat_id}/title", {"title": "Notes on pooling"})
    _, asked, _ = chatgpt_running.post_json("/api/exports", {})
    path = json.loads(asked)["link"].removeprefix("https://chatgpt.com")

    status, refused = chatgpt_running.get_bytes(path)
    assert status == 403
    assert b"Sign in first" in refused

    status, payload = chatgpt_running.get_bytes(path, cookies=True)
    assert status == 200
    assert zipfile.is_zipfile(io.BytesIO(payload))
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert sorted(archive.namelist()) == ["conversations.json", "user.json"]
        conversations = json.loads(archive.read("conversations.json"))
        user = json.loads(archive.read("user.json"))
    assert [conversation["conversation_id"] for conversation in conversations] == [chat_id]
    assert conversations[0]["title"] == "Notes on pooling"
    assert user["email"] == EMAIL

    _, listed, _ = chatgpt_running.request("/__mock/exports.json")
    assert [entry["fetched"] for entry in json.loads(listed)] == [1]


def test_a_link_nobody_asked_for_is_not_found_to_a_session_and_refused_to_none(chatgpt_running: Client) -> None:
    assert chatgpt_running.get_bytes("/__mock/exports/deadbeef.zip")[0] == 403
    sign_in(chatgpt_running)
    assert chatgpt_running.get_bytes("/__mock/exports/deadbeef.zip", cookies=True)[0] == 404


def test_the_links_are_listed_openly_as_text_and_as_json(chatgpt_running: Client) -> None:
    """The listing stands in for the inbox, and the inbox is not the account."""
    sign_in(chatgpt_running)
    _, first, _ = chatgpt_running.post_json("/api/exports", {})
    _, second, _ = chatgpt_running.post_json("/api/exports", {})
    links = [json.loads(first)["link"], json.loads(second)["link"]]
    anyone = Client(chatgpt_running.base)
    _, text, _ = anyone.request("/__mock/exports")
    assert text == "".join(f"{link}\n" for link in links)
    _, payload, _ = anyone.request("/__mock/exports.json")
    listed = json.loads(payload)
    assert [entry["link"] for entry in listed] == links
    assert [entry["requested_at"] for entry in listed] == [WALL, WALL]
    assert all(entry["token"] in entry["link"] for entry in listed)
