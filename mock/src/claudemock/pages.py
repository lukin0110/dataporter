"""The HTML the mock serves, and the one script that makes it a site.

Everything here is shaped by `docs/claude-ui-map.md`, because the tool reads the
page with the selectors that table names: a `div[contenteditable="true"]` for the
composer, `[data-testid="user-message"]` and `[data-testid="assistant-message"]`
for turns, a `Send`/`Stop` pair of `aria-label`s, a hidden `input[type="file"]`,
and `[data-testid="chat-menu-trigger"]` for the title. `uimap.py` cites the row
behind each of them; this module is where they are written down as markup.

The composer is ProseMirror-like, and deliberately so: a bare `contenteditable`
is not what claude.ai has, and Chrome's own editing turns a blank line into
`<div><br></div>` — whose `innerText` reports two line breaks where one was
typed. One paragraph per line and `white-space: pre-wrap` is what makes a 40 kB
seed come back byte for byte, which is the thing a rehearsal is testing.

The script is the site's behaviour in the browser: it submits, it renders turns
as they arrive, it uploads a file and grows a chip for it, and it renames a chat.
Everything it does goes through the mock's own HTTP API, so the ledger counts it.

`32`'s export page is not a page. claude.ai asks for an export from a **settings
dialog over the app**, at a fragment of `/new` — so the panel is markup on the
chat page, shown when the address carries `#settings/data-privacy-controls`, and
the composer and the file input are behind it exactly as they are on the real
site. `31` guessed a path of its own and `51` found it served nothing; `32`'s
`export_page()` was built on that guess and is gone with it.

The panel's selectors are the tool's, re-typed rather than imported (ADR 0003):
`[data-perf-screen="data-privacy-controls"] [data-settings-row] button[data-cds="Button"]`
for the row, `[data-testid="export-confirm-button"]` on the second screen, and
`[data-cds="Toast"] [role="dialog"] h2` for the answer.
"""

import html
import json
from collections.abc import Sequence

from mockcore.reply import Turn

from claudemock.site import Chat

STYLE = """\
  body { font-family: system-ui, sans-serif; margin: 2rem; }
  /* `pre-wrap` so `innerText` reports the spaces and the line breaks that were
     typed, and a paragraph with no margin so it reports one line break per line
     and not the two an unstyled <p> is worth. Both are what ProseMirror sets. */
  div[contenteditable="true"] { white-space: pre-wrap; border: 1px solid #999;
    min-height: 3rem; padding: .5rem; }
  div[contenteditable="true"] p { margin: 0; }
  [data-testid="user-message"], [data-testid="assistant-message"] {
    white-space: pre-wrap; margin: .5rem 0; }
  .attachment-chip { display: inline-block; border: 1px solid #999;
    padding: 0 .3rem; margin: .2rem; }
  /* The settings panel's stages: `hidden` is how the dialog and the toast wait
     their turn, and `.invisible` is a row the panel offers but does not show —
     both `display: none`, which is what the tool's `visible` filter reads. */
  [hidden] { display: none; }
  .invisible { display: none; }
  [data-perf-screen] { border: 1px solid #999; padding: 1rem; margin-bottom: 1rem; }
  [data-settings-row] { display: flex; gap: 1rem; justify-content: space-between;
    padding: .3rem 0; }
  [data-cds="Toast"]:empty { display: none; }
  [data-cds="Toast"] { position: fixed; right: 1rem; bottom: 1rem; }
"""

APP_JS = """\
  const CHAT_ID = __CHAT_ID__;
  const state = { chatId: CHAT_ID, polling: false };

  const composer = document.querySelector('div[contenteditable="true"]');
  const transcript = document.getElementById('transcript');
  const chips = document.getElementById('chips');
  const controls = document.getElementById('controls');

  const currentText = () =>
    composer.children.length === 0
      ? composer.textContent
      : Array.prototype.map
          .call(composer.children, (line) => line.textContent)
          .join('\\n');

  const render = (text) => {
    composer.textContent = '';
    for (const line of text.split('\\n')) {
      const paragraph = document.createElement('p');
      if (line === '') {
        paragraph.appendChild(document.createElement('br'));
      } else {
        paragraph.textContent = line;
      }
      composer.appendChild(paragraph);
    }
    sendable();
  };

  const clear = () => { render(''); };

  /* `can submit`: a Send that is disabled while there is nothing to send, which
     is also what the tool reads as "not rate limited". */
  const sendable = () => {
    const send = document.getElementById('send');
    if (send) send.disabled = currentText().length === 0;
  };

  const generating = (on) => {
    controls.textContent = '';
    const button = document.createElement('button');
    if (on) {
      button.id = 'stop';
      button.setAttribute('aria-label', 'Stop response');
      button.textContent = 'Stop';
    } else {
      button.id = 'send';
      button.setAttribute('aria-label', 'Send message');
      button.textContent = 'Send';
    }
    controls.appendChild(button);
    if (!on) sendable();
  };

  const paint = (turns) => {
    transcript.textContent = '';
    for (const turn of turns) {
      const element = document.createElement('div');
      element.setAttribute(
        'data-testid',
        turn.role === 'human' ? 'user-message' : 'assistant-message'
      );
      element.textContent = turn.text;
      transcript.appendChild(element);
    }
  };

  const poll = () => {
    if (state.polling || state.chatId === null) return;
    state.polling = true;
    const tick = () => {
      fetch('/api/chats/' + state.chatId, { headers: { 'Accept': 'application/json' } })
        .then((answer) => answer.json())
        .then((chat) => {
          paint(chat.turns);
          generating(chat.generating);
          if (chat.generating) {
            window.setTimeout(tick, 250);
          } else {
            state.polling = false;
          }
        })
        .catch(() => { state.polling = false; });
    };
    tick();
  };

  const submit = () => {
    const text = currentText();
    if (text.length === 0) return;
    /* Synchronously, before the request goes out: the turn is on the page and
       the composer is empty by the time the key press returns, which is the
       state the tool probes for immediately afterwards. */
    const turn = document.createElement('div');
    turn.setAttribute('data-testid', 'user-message');
    turn.textContent = text;
    transcript.appendChild(turn);
    clear();
    generating(true);
    const url = state.chatId === null
      ? '/api/chats'
      : '/api/chats/' + state.chatId + '/messages';
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text }),
    })
      .then((answer) => answer.json())
      .then((chat) => {
        if (state.chatId === null) {
          state.chatId = chat.id;
          /* The chat now has a URL, and it is the one the tool reads the
             conversation id off. */
          window.history.replaceState({}, '', '/chat/' + chat.id);
          document.title = chat.title;
          menu(chat.title);
        }
        poll();
      });
  };

  composer.addEventListener('beforeinput', (event) => {
    if (event.inputType !== 'insertText' || event.data === null) return;
    event.preventDefault();
    render(currentText() + event.data);
  });

  composer.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' || event.shiftKey) return;
    event.preventDefault();
    submit();
  });

  document.querySelector('input[type="file"]').addEventListener('change', (event) => {
    for (const file of event.target.files) {
      fetch('/api/uploads', {
        method: 'POST',
        headers: { 'X-File-Name': encodeURIComponent(file.name) },
        body: file,
      }).then(() => {
        /* `upload accepted`: a leaf element outside the composer carrying the
           file's name, and not before the mock has taken the bytes. */
        const chip = document.createElement('div');
        chip.className = 'attachment-chip';
        chip.textContent = file.name;
        chips.appendChild(chip);
      });
    }
  });

  /* `rename affordance`: the chat's own menu, a rename control in it, and a
     field that takes a new name. */
  const menu = (title) => {
    const header = document.getElementById('chat-header');
    if (!header) return;
    header.hidden = false;
    document.getElementById('chat-menu-trigger').textContent = title;
  };

  const trigger = document.getElementById('chat-menu-trigger');
  if (trigger) {
    trigger.addEventListener('click', () => {
      document.getElementById('chat-menu').hidden = false;
    });
    document.getElementById('rename-chat').addEventListener('click', () => {
      const field = document.getElementById('chat-title-input');
      field.hidden = false;
      field.value = '';
      field.focus();
    });
    document.getElementById('chat-title-input').addEventListener('keydown', (event) => {
      if (event.key !== 'Enter') return;
      event.preventDefault();
      const field = event.target;
      const title = field.value;
      fetch('/api/chats/' + state.chatId + '/title', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title }),
      }).then(() => {
        field.hidden = true;
        document.getElementById('chat-menu').hidden = true;
        document.title = title;
        menu(title);
      });
    });
  }

  if (state.chatId !== null) poll();
  sendable();
"""

LOGIN_JS = """\
  const banner = document.getElementById('cookie-banner');
  if (banner) {
    document.getElementById('accept-cookies').addEventListener('click', () => {
      /* Dismissed once, and it stays dismissed: the cookie is what a reload and
         the form's own POST read. */
      document.cookie = 'mock_banner=dismissed; path=/';
      banner.hidden = true;
      document.getElementById('signin').hidden = false;
    });
  }
  /* The link-sent page's two buttons are `type="button"`, as the real page's
     are: each is a request of its own, and then the page is read again. */
  for (const [id, path] of [['resend', '/login/resend'], ['change', '/login/change']]) {
    const button = document.getElementById(id);
    if (button) {
      button.addEventListener('click', () => {
        fetch(path, { method: 'POST' }).then(() => location.reload()).catch(() => {});
      });
    }
  }
"""

MAGIC_LINK_JS = """\
  /* `sign-in link`: the token never reached the server. The page reads it off
     its own fragment, clears the fragment from the address bar as the real page
     does, and posts the pair; the pending sign-in is the browser's cookie. */
  const hash = location.hash.slice(1);
  history.replaceState(null, '', location.pathname + location.search);
  const [token, address] = hash.split(':');
  if (!token || !address) {
    location.replace('/login');
  } else {
    let email = '';
    try {
      email = atob(address.replace(/-/g, '+').replace(/_/g, '/'));
    } catch (error) {
      email = '';
    }
    const body = new URLSearchParams({ token: token, email: email });
    fetch('/login/redeem', { method: 'POST', body: body, credentials: 'same-origin' })
      .then((answer) => answer.json())
      .then((payload) => { location.replace(payload.next || '/login'); })
      .catch(() => { location.replace('/login'); });
  }
"""

SETTINGS_HASH = "#settings/data-privacy-controls"
EXPORT_SCREEN_HASH = SETTINGS_HASH + "/export-data"
"""The two addresses the panel has, and the whole reason it is not a page.

The tool navigates to the first and clicks through to the second, and both the
wall (`sites.extraction_pattern`) and `on_export_page` read the fragment as well
as the path. A mock that showed the second screen without moving the address
would leave the subtree branch of both of them untested."""

SETTINGS_JS = """\
  /* The settings panel (`export page`, `export button`, `export confirmation`,
     `export requested`). Two screens at two addresses, one in the document at a
     time: the second screen replaces the first rather than hiding it, because
     that is what a real trace shows — a sketch taken on the second screen counts
     one confirmation button and no export rows at all. Templates are what make
     that true of `querySelectorAll` and not merely of what is painted. */
  const panel = document.querySelector('[data-perf-screen="data-privacy-controls"]');
  const toast = document.querySelector('[data-cds="Toast"]');
  const screens = {
    '__SETTINGS_HASH__': 'settings-root',
    '__EXPORT_SCREEN_HASH__': 'settings-export',
  };

  function showSettings() {
    const template = screens[location.hash];
    panel.replaceChildren();
    panel.hidden = !template;
    if (!template) return;
    panel.appendChild(document.getElementById(template).content.cloneNode(true));
    const row = panel.querySelector('[data-settings-row] button[data-cds="Button"]:not(.invisible)');
    if (row) row.addEventListener('click', () => { location.hash = '__EXPORT_SCREEN_HASH__'; });
    const confirm = panel.querySelector('[data-testid="export-confirm-button"]');
    if (confirm) confirm.addEventListener('click', askForTheExport);
  }

  function askForTheExport() {
    /* `export requested`: the toast is raised only once the mock has counted the
       ask and minted a link, so the ledger is the witness. The ask answers 202 —
       accepted, not done — which is what the real one answers, so `ok` is read
       from the body rather than from the status. A signed-out POST is redirected
       to the login page, whose body is not JSON, and nothing appears. */
    fetch('/api/exports', { method: 'POST', headers: { 'Accept': 'application/json' } })
      .then((answer) => answer.json())
      .then((payload) => { if (payload.ok) raiseToast('__REQUESTED_TEXT__'); })
      .catch(() => {});
  }

  function raiseToast(words) {
    const note = document.createElement('div');
    note.setAttribute('role', 'dialog');
    const heading = document.createElement('h2');
    heading.textContent = words;
    note.appendChild(heading);
    toast.appendChild(note);
  }

  window.addEventListener('hashchange', showSettings);
  showSettings();
"""

REQUESTED_TEXT = "Export started"
"""What the toast says, in English and in these words.

The one signal the tool reads by its words as well as its shape, because the
container is the site's notification furniture and every toast shares it. A mock
that answered in any other wording — or in the Spanish a real account was served
— would be proving that the selector which ships cannot work, which is a thing to
write in the limitations and not a thing for the mock to do."""


def shell(title: str, body: str, script: str = "") -> bytes:
    """One page. Nothing outside this function writes a `<html>`."""
    tail = f"<script>\n{script}</script>\n" if script else ""
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{html.escape(title)}</title>\n<style>\n{STYLE}</style>\n"
        f"</head>\n<body>\n{body}\n{tail}</body>\n</html>\n"
    ).encode()


# --------------------------------------------------------------------------- #
# The sign-in page (`sign-in form`, `signed out`)
# --------------------------------------------------------------------------- #

PROVIDERS = ("Google", "Apple", "SSO")
"""The paths a sign-in is told never to take. They lead to a page that cannot
sign anybody in, so a run that takes one fails the rehearsal instead of quietly
passing it."""


def login_page(*, step: str, banner: bool, error: str = "", address: str = "") -> bytes:
    """Return the login page at whichever of its two states the browser is at.

    The email step (`sign-in form`): the banner comes first and hides the form
    until it is dismissed, which is the thing `24`'s agent half existed to get
    past, then the email path and the three ways of not taking it. The link-sent
    state (`link sent`, `49`): the controls the real page showed on 2026-09-15,
    re-typed from `docs/spike/claude-sign-in-link-sent.html` — a code field the
    tool reads as a boolean and never types into, a submit, and two buttons for
    resending and changing the address.
    """
    parts: list[str] = []
    alert = f'<p role="alert">{html.escape(error)}</p>\n' if error else ""
    if step == "link_sent":
        parts.append(
            f'<main id="signin">\n<h1>Sign in</h1>\n{alert}'
            '<form id="link-sent" method="post" action="/login/code">\n'
            "  <p>To continue, click the link sent to</p>\n"
            f'  <p class="address">{html.escape(address)}</p>\n'
            '  <p>Did not get the email? <button type="button" id="resend">Try sending it again</button>.</p>\n'
            '  <p>Wrong address? <button type="button" id="change">Change email address</button></p>\n'
            "  <p>If the link shows a verification code instead of signing you in, enter it here.</p>\n"
            '  <input data-testid="code" aria-label="Verification code" '
            'placeholder="Enter verification code" inputmode="numeric" '
            'autocomplete="one-time-code" id="code" name="code" type="text" value="">\n'
            '  <button type="submit" data-testid="continue">Verify email address</button>\n'
            "</form>\n</main>"
        )
        return shell("Sign in", "\n".join(parts), LOGIN_JS)
    if banner:
        parts.append(
            '<div id="cookie-banner" role="region" aria-label="Cookie notice">\n'
            "  <p>We use cookies to make this site work.</p>\n"
            '  <button id="accept-cookies" type="button">Accept all</button>\n'
            "</div>"
        )
    hidden = " hidden" if banner else ""
    buttons = "\n".join(
        f'  <button type="button" formaction="/login/unsupported" '
        f"onclick=\"location.href='/login/unsupported'\">Continue with {name}"
        f"</button>"
        for name in PROVIDERS
    )
    form = (
        '<form id="email-step" method="post" action="/login/email">\n'
        '  <input type="email" name="email" autocomplete="username" '
        'placeholder="Email">\n'
        '  <button type="submit" aria-label="Continue with email">Continue'
        "</button>\n"
        "</form>"
    )
    parts.append(
        f'<main id="signin"{hidden}>\n<h1>Sign in</h1>\n{alert}{buttons}\n'
        '  <button type="button" onclick="location.href=\'/login/unsupported\'">'
        "Use a passkey</button>\n"
        f"{form}\n</main>"
    )
    return shell("Sign in", "\n".join(parts), LOGIN_JS)


def magic_link_page() -> bytes:
    """Return where a sign-in link lands: nothing to see, and a script that spends it (`sign-in link`)."""
    return shell("Sign in", '<main id="magic-link">\n<p>Signing you in…</p>\n</main>', MAGIC_LINK_JS)


def unsupported_page() -> bytes:
    """Where every path but email ends: no form, and nothing to sign in with."""
    return shell(
        "Sign in",
        "<main>\n<h1>Not available</h1>\n"
        "<p>This account signs in with an email address and a link.</p>\n"
        '<p><a href="/login">Back</a></p>\n</main>',
    )


# --------------------------------------------------------------------------- #
# The settings panel (`export page`, `export button`, `export confirmation`,
# `export period`, `export requested`)
# --------------------------------------------------------------------------- #

MANAGE_ROWS = ("Manage memories", "Manage projects", "Manage connectors", "Manage devices")
"""The rows under Export, each offering a button that does not ask for anything.

They are why the export button is matched by *position* and not by a test id: the
panel gives the tool nothing to tell the Export row from these, so the selector
takes the first visible match and the mock's job is to make that claim a real
one. Four of them here and five on the real account, because one of the six
buttons the panel really shows is spent on the invisible row below."""

PERIODS = (("All", True), ("Last 30 days", False), ("Last 90 days", False), ("Custom", False))
"""The second screen's `Conversations from`, with `All` the default.

The ask touches none of it and relies on that default. If claude.ai ever changed
it, `extract` would start filing partial snapshots while reporting success — so
the control is here to be seen in a sketch, and the mock leaves it exactly as
unread as the tool does."""


def _settings_row(label: str, control: str, *, invisible: bool = False) -> str:
    attributes = ' data-settings-row class="invisible"' if invisible else " data-settings-row"
    return f"  <div{attributes}>\n    <span>{html.escape(label)}</span>\n    {control}\n  </div>"


def settings_root() -> str:
    """Return the panel's first screen: six buttons, of which the Export row is the first visible.

    **Six**, which is what a sketch of the real panel counts, and the tool's
    selector matches every one of them. The first is invisible — a row the account
    does not have — so that `click_js` pressing *the first visible match* is a
    claim this page can falsify rather than one it happens to satisfy. `32` made
    that point with a hidden twin of the one button; a twin would make seven, and
    the count is the thing a sketch can be laid beside.

    Above them a row holding a switch rather than a button, because that is the
    shape the Export row's position depends on: every row above it holds one.
    """
    rows = [
        _settings_row("Export data", '<button data-cds="Button">Export data</button>', invisible=True),
        _settings_row(
            "Help improve Claude",
            '<button role="switch" aria-checked="false">Off</button>',
        ),
        _settings_row("Export data", '<button data-cds="Button">Export data</button>'),
        *(_settings_row(label, '<button data-cds="Button">Manage</button>') for label in MANAGE_ROWS),
    ]
    return "\n".join(["  <h2>Privacy</h2>", *rows])


def settings_export_screen() -> str:
    """Return the second screen: what the export will include, the period, and the button that asks."""
    periods = "\n".join(
        f'    <label><input type="radio" name="period" value="{html.escape(label)}"'
        f"{' checked' if checked else ''}> {html.escape(label)}</label>"
        for label, checked in PERIODS
    )
    return (
        "  <h2>Export data</h2>\n"
        "  <p>You will receive an email with a link to download your data.</p>\n"
        '  <div role="radiogroup" aria-label="Conversations from">\n'
        f"{periods}\n"
        "  </div>\n"
        '  <button type="button" data-testid="export-confirm-button">Export</button>'
    )


def settings_panel() -> str:
    """Return the panel, its two screens as templates, and the toast that answers.

    The panel is empty until the address says which screen to show, and a
    `<template>`'s content is not in the document — so `querySelectorAll` counts
    what is on screen and nothing else, which is what makes the counts here the
    counts a sketch of the real panel took.
    """
    return (
        '<div data-perf-screen="data-privacy-controls" role="dialog" aria-label="Settings" hidden></div>\n'
        '<template id="settings-root">\n'
        f"{settings_root()}\n"
        "</template>\n"
        '<template id="settings-export">\n'
        f"{settings_export_screen()}\n"
        "</template>\n"
        '<div data-cds="Toast"></div>'
    )


# --------------------------------------------------------------------------- #
# The chat pages (`new chat`, `conversation`)
# --------------------------------------------------------------------------- #


def _turns(turns: Sequence[Turn]) -> str:
    return "\n".join(
        f'  <div data-testid="{"user" if turn.role == "human" else "assistant"}-message">{html.escape(turn.text)}</div>'
        for turn in turns
    )


def _chips(names: Sequence[str]) -> str:
    return "".join(f'<div class="attachment-chip">{html.escape(name)}</div>' for name in names)


def _header(chat: Chat | None) -> str:
    """Return the chat's own menu, which is also where its title is shown."""
    hidden = "" if chat is not None else " hidden"
    title = html.escape(chat.title) if chat is not None else ""
    return (
        f'<header id="chat-header"{hidden}>\n'
        f'  <button id="chat-menu-trigger" data-testid="chat-menu-trigger">'
        f"{title}</button>\n"
        '  <div id="chat-menu" role="menu" hidden>\n'
        '    <button id="rename-chat" data-testid="rename-chat">Rename</button>\n'
        "  </div>\n"
        '  <input id="chat-title-input" data-testid="chat-title-input" type="text" '
        'placeholder="Chat name" hidden>\n'
        "</header>"
    )


def chat_page(chat: Chat | None, turns: Sequence[Turn], *, generating: bool) -> bytes:
    """Return `/new` when `chat` is `None`, and `/chat/<uuid>` when it is not.

    One function for both because they are one page: the only difference is
    whether there is a chat behind it yet, which is exactly what a submit
    changes without a reload.

    The settings panel is on both of them, closed, because claude.ai's export is
    a dialog over the app and not a page (§77). It opens on the address alone, so
    a navigation to `/new#settings/data-privacy-controls` and a hash change from
    `/new` reach it by the same door — which is the two ways the tool arrives.
    """
    control = (
        '<button id="stop" aria-label="Stop response">Stop</button>'
        if generating
        else '<button id="send" aria-label="Send message" disabled>Send</button>'
    )
    body = "\n".join([
        _header(chat),
        settings_panel(),
        "<main>",
        '  <div id="transcript" data-testid="conversation">',
        _turns(turns),
        "  </div>",
        '  <div contenteditable="true" role="textbox" aria-label="Write your prompt"><p><br></p></div>',
        '  <input type="file" multiple style="display: none">',
        f'  <div id="chips">{_chips(chat.files if chat else ())}</div>',
        f'  <div id="controls">{control}</div>',
        "</main>",
    ])
    title = chat.title if chat is not None else "New chat"
    script = "\n".join([
        APP_JS.replace("__CHAT_ID__", json.dumps(chat.id) if chat is not None else "null"),
        SETTINGS_JS
        .replace("__SETTINGS_HASH__", SETTINGS_HASH)
        .replace("__EXPORT_SCREEN_HASH__", EXPORT_SCREEN_HASH)
        .replace("__REQUESTED_TEXT__", REQUESTED_TEXT),
    ])
    return shell(title, body, script)
