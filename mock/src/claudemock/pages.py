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

`32`'s export page is the one page here with no composer. It is built out of the
four `31` rows — a button, a confirmation, a status — spelled with the selectors
the tool's `export_page.py` looks for, re-typed rather than imported (ADR 0003).
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
  /* The export page's stages: `hidden` is how a dialog and a status region
     wait their turn, and `.invisible` is a control the page offers but does not
     show — both `display: none`, which is what the tool's `visible` filter
     reads. */
  [hidden] { display: none; }
  .invisible { display: none; }
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

EXPORT_JS = """\
  const dialog = document.querySelector('[role="dialog"]');
  const requested = document.querySelector('[data-testid="export-requested"]');
  for (const button of document.querySelectorAll('[data-testid="export-data"]')) {
    button.addEventListener('click', () => { dialog.hidden = false; });
  }
  document.querySelector('[data-testid="confirm-export"]').addEventListener('click', () => {
    /* `export requested`: the status region appears only once the mock has
       counted the ask and minted a link, so the ledger is the witness. A
       signed-out POST is redirected to the login page, whose body is not JSON,
       and nothing appears. */
    fetch('/api/exports', { method: 'POST', headers: { 'Accept': 'application/json' } })
      .then((answer) => answer.json())
      .then((payload) => {
        if (!payload.ok) return;
        dialog.hidden = true;
        requested.hidden = false;
      })
      .catch(() => {});
  });
"""


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
# The export page (`export page`, `export button`, `export confirmation`,
# `export requested`)
# --------------------------------------------------------------------------- #


def export_page() -> bytes:
    """Return the page where the account's data is asked for, at its first stage.

    Three stages, walked by the page's own script: a button, a dialog with a
    confirmation in it, and a status region that appears once the ask has been
    taken. A hidden twin of the button comes first in the DOM, because a page that
    offers one control per device width is exactly how a real one would break a
    click helper that did not filter by visibility — and the tool's does.

    No composer, no file input, no other dialog and no other status: the tool
    reads the page as four booleans, and anything else visible here would be
    something for one of them to be wrong about.
    """
    body = (
        "<main>\n"
        "<h1>Data privacy controls</h1>\n"
        '<button class="invisible" data-testid="export-data">Export data</button>\n'
        '<button data-testid="export-data">Export data</button>\n'
        '<div role="dialog" aria-label="Export data" hidden>\n'
        "  <p>Claude will email a download link to the address on this account.</p>\n"
        '  <button type="submit" data-testid="confirm-export">Confirm</button>\n'
        "</div>\n"
        '<div role="status" data-testid="export-requested" hidden>\n'
        "  Your export was requested. Check your email.\n"
        "</div>\n"
        "</main>"
    )
    return shell("Data privacy controls", body, EXPORT_JS)


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
    """
    control = (
        '<button id="stop" aria-label="Stop response">Stop</button>'
        if generating
        else '<button id="send" aria-label="Send message" disabled>Send</button>'
    )
    body = "\n".join([
        _header(chat),
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
    script = APP_JS.replace("__CHAT_ID__", json.dumps(chat.id) if chat is not None else "null")
    return shell(title, body, script)
