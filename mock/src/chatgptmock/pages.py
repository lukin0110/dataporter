"""The HTML the mock chatgpt.com serves, and the one script that makes it a site.

Everything here is shaped by `docs/chatgpt-ui-map.md`, selector for selector out
of its middle column — the mock's spelling of what the sources report: a
`div#prompt-textarea[contenteditable="true"]` composer, one send-and-stop
control that changes what it is called, `div[data-message-author-role]` turns
with a copy control on a finished one, a hidden `input[type="file"]` behind
**Add files and more**, the sidebar entry with its options menu and its
**Chat title** field, and the export page's **Export** → **Confirm export** →
status. `uimap.py` cites the row behind each of them; this module is where they
are written down as markup.

The composer is ProseMirror-like, and deliberately so: a bare `contenteditable`
is not what the sources report, and Chrome's own editing turns a blank line into
`<div><br></div>` — whose `innerText` reports two line breaks where one was
typed. One paragraph per line and `white-space: pre-wrap` is what makes a 40 kB
seed come back byte for byte, which is the thing a rehearsal is testing.

**A long paste becomes an attachment.** The script applies OpenAI's documented
rule (6825453) to *any* insertion that takes the composer past the threshold —
stricter than the site can be and never laxer (§54): the inserted text becomes a
chip outside the composer with a **Show in text field** control, and the reply
the site writes reads the chip's text too.

Everything the script does goes through the mock's own HTTP API, so the ledger
counts it.
"""

import html
import json
from collections.abc import Sequence
from itertools import starmap

from chatgptmock import AUTH_ORIGIN
from chatgptmock.site import PASTE_THRESHOLD, Chat, Message

STYLE = """\
  body { font-family: system-ui, sans-serif; margin: 0; display: flex; min-height: 100vh; }
  nav#sidebar { width: 16rem; padding: 1rem; border-right: 1px solid #ddd; }
  nav#sidebar ol { list-style: none; padding: 0; }
  nav#sidebar li { margin: .3rem 0; }
  main { flex: 1; padding: 2rem; }
  /* `pre-wrap` so `innerText` reports the spaces and the line breaks that were
     typed, and a paragraph with no margin so it reports one line break per line
     and not the two an unstyled <p> is worth. Both are what ProseMirror sets. */
  #prompt-textarea { white-space: pre-wrap; border: 1px solid #999; min-height: 3rem; padding: .5rem; }
  #prompt-textarea p { margin: 0; }
  .whitespace-pre-wrap, .markdown { white-space: pre-wrap; }
  [data-message-author-role] { margin: .5rem 0; }
  .attachment-chip { display: inline-block; border: 1px solid #999; padding: 0 .3rem; margin: .2rem; }
  /* `hidden` is how a menu, a dialog and a status region wait their turn:
     `display: none`, which is what a visibility filter reads. */
  [hidden] { display: none; }
"""

APP_JS = """\
  const CHAT_ID = __CHAT_ID__;
  const THRESHOLD = __THRESHOLD__;
  const state = { chatId: CHAT_ID, polling: false, generating: false, pasted: [], files: [] };

  const composer = document.getElementById('prompt-textarea');
  const thread = document.getElementById('thread');
  const attachments = document.getElementById('attachments');
  const control = document.getElementById('composer-submit-button');
  const history = document.getElementById('history');

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

  /* `can submit`: a send control that is disabled while there is nothing to
     send — nothing typed, nothing pasted, nothing attached. */
  const sendable = () => {
    if (state.generating) return;
    control.disabled =
      currentText().length === 0 && state.pasted.length === 0 && state.files.length === 0;
  };

  /* `generating`: one element that changes what it is called, not two. */
  const setControl = (generating) => {
    state.generating = generating;
    if (generating) {
      control.setAttribute('data-testid', 'stop-button');
      control.setAttribute('aria-label', 'Stop streaming');
      control.textContent = 'Stop';
      control.disabled = false;
    } else {
      control.setAttribute('data-testid', 'send-button');
      control.setAttribute('aria-label', 'Send prompt');
      control.textContent = 'Send';
      sendable();
    }
  };

  const chip = (label) => {
    const element = document.createElement('div');
    element.className = 'attachment-chip';
    element.textContent = label;
    return element;
  };

  /* `human turn`, `assistant turn`, `generation finished`: a turn by role, and
     a copy control on a turn the page says is finished. */
  const turnElement = (message, finished) => {
    const turn = document.createElement('div');
    turn.setAttribute('data-message-author-role', message.role);
    const text = document.createElement('div');
    text.className = message.role === 'user' ? 'whitespace-pre-wrap' : 'markdown';
    text.textContent = message.text;
    turn.appendChild(text);
    for (const pasted of message.pasted || []) {
      const attachment = chip('Pasted text');
      attachment.setAttribute('data-testid', 'pasted-text-attachment');
      const body = document.createElement('div');
      body.className = 'whitespace-pre-wrap';
      body.textContent = pasted;
      attachment.appendChild(body);
      turn.appendChild(attachment);
    }
    for (const name of message.files || []) turn.appendChild(chip(name));
    if (message.role === 'assistant' && finished) {
      const copy = document.createElement('button');
      copy.type = 'button';
      copy.setAttribute('data-testid', 'copy-turn-action-button');
      copy.setAttribute('aria-label', 'Copy response');
      copy.textContent = 'Copy';
      turn.appendChild(copy);
    }
    return turn;
  };

  const paint = (chat) => {
    thread.textContent = '';
    chat.turns.forEach((message, index) => {
      const last = index === chat.turns.length - 1;
      thread.appendChild(turnElement(message, !(chat.generating && last)));
    });
  };

  const poll = () => {
    if (state.polling || state.chatId === null) return;
    state.polling = true;
    const tick = () => {
      fetch('/api/chats/' + state.chatId, { headers: { 'Accept': 'application/json' } })
        .then((answer) => answer.json())
        .then((chat) => {
          paint(chat);
          setControl(chat.generating);
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
    const pasted = state.pasted.map((item) => item.text);
    const files = state.files.slice();
    if (text.length === 0 && pasted.length === 0 && files.length === 0) return;
    /* Synchronously, before the request goes out: the turn is on the page and
       the composer is empty by the time the key press returns. */
    thread.appendChild(turnElement({ role: 'user', text: text, pasted: pasted, files: files }, true));
    state.pasted = [];
    state.files = [];
    attachments.textContent = '';
    clear();
    setControl(true);
    const url = state.chatId === null
      ? '/api/chats'
      : '/api/chats/' + state.chatId + '/messages';
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text, pasted: pasted }),
    })
      .then((answer) => answer.json())
      .then((chat) => {
        if (state.chatId === null) {
          state.chatId = chat.id;
          /* `conversation`: the chat now has a URL of its own. */
          window.history.replaceState({}, '', '/c/' + chat.id);
          document.title = chat.title;
          history.insertBefore(entryElement(chat.id, chat.title), history.firstChild);
          renumber();
        }
        poll();
      });
  };

  const stop = () => {
    fetch('/api/chats/' + state.chatId + '/stop', { method: 'POST' })
      .then((answer) => answer.json())
      .then((chat) => { paint(chat); setControl(false); });
  };

  control.addEventListener('click', () => { if (state.generating) stop(); else submit(); });

  /* `paste over the threshold`: the inserted text becomes an attachment when it
     would take the composer past the threshold, whatever inserted it. */
  const attachPasted = (text) => {
    const item = { text: text };
    state.pasted.push(item);
    const attachment = chip('Pasted text');
    attachment.setAttribute('data-testid', 'pasted-text-attachment');
    const show = document.createElement('button');
    show.type = 'button';
    show.textContent = 'Show in text field';
    show.addEventListener('click', () => {
      state.pasted.splice(state.pasted.indexOf(item), 1);
      attachment.remove();
      render(currentText() + item.text);
    });
    attachment.appendChild(show);
    attachments.appendChild(attachment);
    sendable();
  };

  const insert = (data) => {
    const next = currentText() + data;
    if (next.length > THRESHOLD) {
      attachPasted(data);
    } else {
      render(next);
    }
  };

  composer.addEventListener('beforeinput', (event) => {
    let data = null;
    if (event.inputType === 'insertText') {
      data = event.data;
    } else if (event.inputType === 'insertFromPaste' && event.dataTransfer) {
      data = event.dataTransfer.getData('text/plain');
    }
    if (data === null || data === '') return;
    event.preventDefault();
    insert(data);
  });

  composer.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' || event.shiftKey) return;
    event.preventDefault();
    if (!state.generating) submit();
  });

  /* `upload target`, `upload accepted`. */
  const fileInput = document.querySelector('input[type="file"]');
  document.querySelector('[data-testid="composer-plus-btn"]').addEventListener('click', () => {
    fileInput.click();
  });
  fileInput.addEventListener('change', (event) => {
    for (const file of event.target.files) {
      fetch('/api/uploads', {
        method: 'POST',
        headers: { 'X-File-Name': encodeURIComponent(file.name) },
        body: file,
      }).then(() => {
        /* A leaf element outside the composer carrying the file's name, and
           not before the mock has taken the bytes. */
        state.files.push(file.name);
        attachments.appendChild(chip(file.name));
        sendable();
      });
    }
  });

  /* `chat title`, `rename affordance`: the sidebar entry, its options menu, its
     Rename item, and the titled field behind it. */
  const entryElement = (id, title) => {
    const entry = document.createElement('li');
    entry.dataset.chatId = id;
    const link = document.createElement('a');
    link.href = '/c/' + id;
    link.setAttribute('aria-label', title);
    link.textContent = title;
    const options = document.createElement('button');
    options.type = 'button';
    options.setAttribute('aria-label', 'Open conversation options');
    options.textContent = '\\u2026';
    const menu = document.createElement('div');
    menu.setAttribute('role', 'menu');
    menu.hidden = true;
    for (const action of ['Share', 'Rename', 'Archive', 'Delete']) {
      const item = document.createElement('div');
      item.setAttribute('role', 'menuitem');
      item.dataset.action = action.toLowerCase();
      item.textContent = action;
      menu.appendChild(item);
    }
    const field = document.createElement('input');
    field.type = 'text';
    field.setAttribute('aria-label', 'Chat title');
    field.hidden = true;
    entry.append(link, options, menu, field);
    wireEntry(entry);
    return entry;
  };

  const renumber = () => {
    Array.prototype.forEach.call(history.children, (entry, position) => {
      entry.querySelector('button').setAttribute('data-testid', 'history-item-' + position + '-options');
    });
  };

  const wireEntry = (entry) => {
    const link = entry.querySelector('a');
    const options = entry.querySelector('button');
    const menu = entry.querySelector('[role="menu"]');
    const field = entry.querySelector('input[aria-label="Chat title"]');
    options.addEventListener('click', () => { menu.hidden = !menu.hidden; });
    for (const item of menu.querySelectorAll('[role="menuitem"]')) {
      item.addEventListener('click', () => {
        menu.hidden = true;
        if (item.dataset.action !== 'rename') return;
        field.hidden = false;
        field.value = link.getAttribute('aria-label');
        field.focus();
        field.select();
      });
    }
    field.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        field.hidden = true;
        return;
      }
      if (event.key !== 'Enter') return;
      event.preventDefault();
      const title = field.value;
      if (title.length === 0) return;
      fetch('/api/chats/' + entry.dataset.chatId + '/title', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title }),
      }).then(() => {
        field.hidden = true;
        link.setAttribute('aria-label', title);
        link.textContent = title;
        if (entry.dataset.chatId === state.chatId) document.title = title;
      });
    });
  };

  for (const entry of history.children) wireEntry(entry);

  /* `settings`: the profile menu, with Settings in it. */
  document.querySelector('[data-testid="profile-button"]').addEventListener('click', () => {
    const menu = document.getElementById('profile-menu');
    menu.hidden = !menu.hidden;
  });

  if (state.chatId !== null) poll();
  sendable();
"""

EXPORT_JS = """\
  const dialog = document.querySelector('[role="dialog"]');
  const requested = document.getElementById('export-requested');
  document.getElementById('export').addEventListener('click', () => { dialog.hidden = false; });
  document.getElementById('confirm-export').addEventListener('click', () => {
    /* `export requested`: the status region appears only once the mock has
       counted the ask and minted a link, so the ledger is the witness. A
       signed-out POST is redirected to the landing page, whose body is not
       JSON, and nothing appears. */
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


def _go(url: str) -> str:
    return f"onclick=\"location.href='{html.escape(url, quote=True)}'\""


# --------------------------------------------------------------------------- #
# The landing page (`signed out`) and the sign-in on the auth host
# (`auth host`, `email step`, `password step`, `other providers`)
# --------------------------------------------------------------------------- #

LOG_IN_PATH = "/log-in"
UNSUPPORTED_PATH = "/log-in/unsupported"
"""Paths on the auth host, picked by `39` and marked *unknown* on the map: what
those pages look like has not been observed by anyone who can be cited."""

PROVIDERS = ("Google", "Microsoft", "Apple")
"""The paths the unattended sign-in is told never to take. They lead to a page
that cannot sign anybody in, so a run that takes one fails instead of quietly
passing."""


def landing_page() -> bytes:
    """Return the site root, signed out: a Log in control, and a Sign up that leads nowhere useful."""
    body = (
        "<main>\n"
        "<h1>ChatGPT</h1>\n"
        f'<button type="button" data-testid="login-button" {_go(AUTH_ORIGIN + LOG_IN_PATH)}>Log in</button>\n'
        f'<button type="button" data-testid="signup-button" {_go(AUTH_ORIGIN + UNSUPPORTED_PATH)}>Sign up</button>\n'
        "</main>"
    )
    return shell("ChatGPT", body)


def login_page(*, step: str, error: str = "") -> bytes:
    """Return the sign-in at whichever of its two steps the session is at, on the auth host.

    The email step and the password step, each with a **Continue** control, and
    the three providers that lead nowhere useful (§54, *Sign-in*). No banner:
    no source reports one.
    """
    alert = f'<p role="alert">{html.escape(error)}</p>\n' if error else ""
    if step == "password":
        heading = "Enter your password"
        form = (
            f'<form id="password-step" method="post" action="{LOG_IN_PATH}/password">\n'
            '  <input type="password" name="password" autocomplete="current-password" placeholder="Password">\n'
            '  <button type="submit">Continue</button>\n'
            "</form>"
        )
    else:
        heading = "Log in"
        form = (
            f'<form id="email-step" method="post" action="{LOG_IN_PATH}/email">\n'
            '  <input type="email" name="email" autocomplete="username" placeholder="Email address">\n'
            '  <button type="submit">Continue</button>\n'
            "</form>"
        )
    buttons = "\n".join(
        f'  <button type="button" {_go(UNSUPPORTED_PATH)}>Continue with {name}</button>' for name in PROVIDERS
    )
    return shell(heading, f'<main id="signin">\n<h1>{heading}</h1>\n{alert}{form}\n{buttons}\n</main>')


def unsupported_page() -> bytes:
    """Where every path but email ends: no form, and nothing to sign in with."""
    return shell(
        "Log in",
        "<main>\n<h1>Not available</h1>\n"
        "<p>This account signs in with an email address and a password.</p>\n"
        f'<p><a href="{LOG_IN_PATH}">Back</a></p>\n</main>',
    )


# --------------------------------------------------------------------------- #
# The chat pages (`new chat`, `conversation`)
# --------------------------------------------------------------------------- #


def _turn(message: Message, *, finished: bool) -> str:
    """One turn, server-rendered as the script would render it."""
    role = message.role
    text_class = "whitespace-pre-wrap" if role == "user" else "markdown"
    parts = [
        f'  <div data-message-author-role="{role}">',
        f'    <div class="{text_class}">{html.escape(message.text)}</div>',
    ]
    parts.extend(
        '    <div class="attachment-chip" data-testid="pasted-text-attachment">Pasted text'
        f'<div class="whitespace-pre-wrap">{html.escape(pasted)}</div></div>'
        for pasted in message.pasted
    )
    parts.extend(f'    <div class="attachment-chip">{html.escape(upload.name)}</div>' for upload in message.files)
    if role == "assistant" and finished:
        parts.append(
            '    <button type="button" data-testid="copy-turn-action-button" aria-label="Copy response">Copy</button>'
        )
    parts.append("  </div>")
    return "\n".join(parts)


def _thread(messages: Sequence[Message], *, generating: bool) -> str:
    last = len(messages) - 1
    return "\n".join(
        _turn(message, finished=not (generating and index == last)) for index, message in enumerate(messages)
    )


def _entry(position: int, chat: Chat) -> str:
    """One sidebar entry: the title as its link, the options button, the menu, the field."""
    title = html.escape(chat.title, quote=True)
    items = "".join(
        f'<div role="menuitem" data-action="{action.lower()}">{action}</div>'
        for action in ("Share", "Rename", "Archive", "Delete")
    )
    return (
        f'    <li data-chat-id="{chat.id}">'
        f'<a href="/c/{chat.id}" aria-label="{title}">{title}</a>'
        f'<button type="button" data-testid="history-item-{position}-options" aria-label="Open conversation options">&hellip;</button>'
        f'<div role="menu" hidden>{items}</div>'
        '<input type="text" aria-label="Chat title" hidden>'
        "</li>"
    )


def _sidebar(chats: Sequence[Chat]) -> str:
    entries = "\n".join(starmap(_entry, enumerate(chats)))
    return (
        '<nav id="sidebar">\n'
        '  <a data-testid="create-new-chat-button" href="/">New chat</a>\n'
        '  <ol id="history">\n'
        f"{entries}\n"
        "  </ol>\n"
        '  <button type="button" data-testid="profile-button" aria-label="Open profile menu">Account</button>\n'
        '  <div id="profile-menu" role="menu" hidden><a role="menuitem" href="/settings">Settings</a></div>\n'
        "</nav>"
    )


def chat_page(chat: Chat | None, messages: Sequence[Message], *, generating: bool, sidebar: Sequence[Chat]) -> bytes:
    """Return `/` when `chat` is `None`, and `/c/<uuid>` when it is not.

    One function for both because they are one page: the only difference is
    whether there is a chat behind it yet, which is exactly what a submit
    changes without a reload.
    """
    control = (
        '<button type="button" id="composer-submit-button" data-testid="stop-button" aria-label="Stop streaming">Stop</button>'
        if generating
        else '<button type="button" id="composer-submit-button" data-testid="send-button" aria-label="Send prompt" disabled>Send</button>'
    )
    body = "\n".join([
        _sidebar(sidebar),
        "<main>",
        '  <div id="thread">',
        _thread(messages, generating=generating),
        "  </div>",
        '  <div id="composer">',
        '    <button type="button" data-testid="composer-plus-btn" aria-label="Add files and more">+</button>',
        '    <input type="file" multiple style="display: none">',
        '    <div id="prompt-textarea" contenteditable="true" role="textbox" aria-label="Message ChatGPT"><p><br></p></div>',
        '    <div id="attachments"></div>',
        f'    <div id="controls">{control}</div>',
        "  </div>",
        "</main>",
    ])
    title = chat.title if chat is not None else "ChatGPT"
    script = APP_JS.replace("__CHAT_ID__", json.dumps(chat.id) if chat is not None else "null").replace(
        "__THRESHOLD__", str(PASTE_THRESHOLD)
    )
    return shell(title, body, script)


# --------------------------------------------------------------------------- #
# Settings (`settings`) and the export page (`export page`, `export button`,
# `export confirmation`, `export requested`)
# --------------------------------------------------------------------------- #

SETTINGS_PATH = "/settings"
EXPORT_PAGE_PATH = "/settings/data-controls"
"""A page of its own, at a path `40` picked: whether the site's Data controls is
a page or a dialog at a hash route was not observed."""


def settings_page() -> bytes:
    """Return Settings: its entries, Data controls among them."""
    body = (
        "<main>\n<h1>Settings</h1>\n<nav>\n"
        f'  <a href="{SETTINGS_PATH}">General</a>\n'
        f'  <a href="{EXPORT_PAGE_PATH}">Data controls</a>\n'
        "</nav>\n</main>"
    )
    return shell("Settings", body)


def export_page() -> bytes:
    """Return Data controls at its first stage: the switch, the Export control, the rest hidden.

    Three stages, walked by the page's own script: **Export**, a dialog with
    **Confirm export** in it, and a status region that appears once the ask has
    been taken. No composer and no file input.
    """
    body = (
        "<main>\n"
        "<h1>Data controls</h1>\n"
        '<label><input type="checkbox" role="switch" checked> Improve the model for everyone</label>\n'
        "<section>\n"
        "  <h2>Export data</h2>\n"
        '  <button type="button" id="export">Export</button>\n'
        "</section>\n"
        '<div role="dialog" aria-label="Request data export" hidden>\n'
        "  <p>Your account details and conversations will be included in the export. "
        "A download link will be sent to the email on this account.</p>\n"
        '  <button type="button" id="confirm-export">Confirm export</button>\n'
        "</div>\n"
        '<div role="status" id="export-requested" hidden>\n'
        "  Your data export has been requested. You will get an email when it is ready.\n"
        "</div>\n"
        "</main>"
    )
    return shell("Data controls", body, EXPORT_JS)
