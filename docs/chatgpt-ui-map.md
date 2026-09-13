# The chatgpt.com UI map

**Kind:** Research record — what OpenAI documents and what others report about chatgpt.com,
not what anyone here has observed. Produced for [brief `05`](../specs/05-chatgpt-mock.md).
**Spike run:** none. **Trace cited:** none.
**Sources read:** 2026-09-13. The help-centre articles were read through a text proxy, since
`help.openai.com` refuses a direct fetch; their titles and "Updated" lines matched, and a
person should still eyeball each one in a browser before a slice pins a row on it.

This is the file the mock chatgpt.com is built out of (§54): every state the mock can show
is a row below, cited in its own citation table, and a behaviour it needs that has no row
here is added here first. It is also the file the tool's ChatGPT half, when it is written,
is corrected against: its selectors will have exactly one spelling in the tool's source and
one in the mock's, re-typed on each side of ADR 0003's line, so correcting a row here is one
edit in each. Nothing here is a design decision; when the map and either side disagree, the
map wins and the code changes.

## Marks

Every row's signal carries one of three, as §54 defines them:

- ***observed on \<date\>*** — a person watched the site do it, or read it in a trace of a
  run against chatgpt.com committed under [`spike/traces/`](spike/traces/) and cites the
  trace by file and line (brief `04` §49);
- ***reported (source, \<date\>)*** — OpenAI's own documentation, or a third party who
  looked, named by the short name in the *Sources* table below and dated by the source's
  own date where it has one and by the reading otherwise. Better than a guess and not an
  observation;
- ***unknown*** — nobody has looked, and the mock takes the simplest behaviour the shape
  admits and says so.

A row's mark is the mark of its signal. Where the signal is *reported* but a named part
of it is not — a path, a trigger, a wording, a redirect chain — the row says so after a
semicolon with a second mark naming the part (`*reported (…)*; the path *unknown*`), and
a slice treats that part as *unknown*: served in the simplest shape, and never claimed.

**A mock run never turns a *reported* or an *unknown* row *observed*.** A walk of the mock
by hand (§56) does not either. Only a person watching chatgpt.com, or reading a trace of a
run against it, marks a row *observed*.

## State → observable signal

The middle column is what the mock serves today; the third is what the sources say the site
does, in the source's own words where they can be quoted. Selectors in the middle column are
the mock's spelling of the reported ones; a later trace's `selectors` object counts them on
the real page.

### Sign-in

| State | Signal the mock serves | Reported signal | Mark |
| ----- | ---------------------- | --------------- | ---- |
| `signed out` | the landing page at the site root with a **Log in** control; every other path answers with a redirect to it | a **Log in** button and a **Sign up** button on the landing page; `chatgpt.com/auth/login` is a live page titled "Get started"; the button reported as `button[data-testid="login-button"]` | *reported (CatGPT-Gateway, 2026-09-13)* |
| `auth host` | the email and password steps are served under `auth.openai.com`, which the mock answers beside `chatgpt.com` (§54) | to sign in, cookies and JavaScript must be allowed for `chatgpt.com`, `openai.com` and `auth.openai.com`; the redirect chain between the hosts was not observed, since the site refuses a scripted fetch | *reported (OpenAI 7426629, 2026-09-13)*; the chain *unknown* |
| `email step` | a visible `input[type="email"]` and a **Continue** button; Enter submits | not looked at; no source cites a field | *unknown* |
| `password step` | a visible `input[type="password"]` and a **Continue** button; Enter submits; a wrong pair is refused back to the email step | not looked at | *unknown* |
| `other providers` | **Continue with Google**, **Continue with Microsoft**, **Continue with Apple** buttons that lead to an unsupported page | the three buttons on the sign-in page | *reported (CatGPT-Gateway, 2026-09-13)* |
| `code or challenge at sign-in` | nothing | not documented; plausible as a risk-based step | *unknown* |
| `cookie banner` | nothing | no source reports one | *unknown* |

### Chats

| State | Signal the mock serves | Reported signal | Mark |
| ----- | ---------------------- | --------------- | ---- |
| `new chat` | path is `/` | a new chat at the site root; a **New chat** link, `a[data-testid="create-new-chat-button"]`, `a[href="/"]` | *reported (CatGPT-Gateway, 2026-09-13)* |
| `conversation` | path matches `/c/<uuid>` | two saved DOM snapshots at `chatgpt.com/c/<uuid>`, the id a version-4 UUID; sidebar links `a[href^="/c/"]` | *reported (Clio, 2026-09-05)* |
| `composer present` | a visible `div#prompt-textarea[contenteditable="true"]`, ProseMirror-shaped: one `<p>` a line, `white-space: pre-wrap` | `#prompt-textarea`, a contenteditable ProseMirror root — **and reported gone** after the site's composer redesign, verified 2026-09-04: "`#prompt-textarea` no longer exists"; a fallback chain of `[contenteditable="true"]`, `textarea`, `[data-testid*="composer"]`, a Lexical root; the replacement is described by nobody yet. The highest-risk row on this map | *reported (CatGPT-Gateway; Clio, 2026-09-05; the drift: webgpt2mcp #4 and crapscraper #210, 2026-09-05)* |
| `composer empty` | the composer's text length is 0 | not looked at | *unknown* |
| `can submit` | a visible `button[data-testid="send-button"]`, also `#composer-submit-button`, `aria-label` **Send prompt**, not disabled | the same three, kept as an ordered fallback chain | *reported (CatGPT-Gateway, 2026-09-13)* |
| `generating` | the same element, now `data-testid="stop-button"`, `aria-label` **Stop streaming** | `button[data-testid="stop-button"]`; labels seen: **Stop answering**, **Stop generating**, **Stop streaming**; send and stop are one element swapping its `data-testid` | *reported (CatGPT-Gateway, 2026-09-13)* |
| `generation finished` | the send-and-stop control is **send** again, and the last turn carries a copy control, `button[data-testid="copy-turn-action-button"]`, `aria-label` **Copy response** | the stop button flips back to send; a copy control appears on the finished turn, called "the most reliable completion signal" in the DOM; the bare label **Copy** is not used because a code block's own copy button carries it too; and "a turn is finished only when the page says so — silence is not completion": the page's own end-of-turn bit is the authority | *reported (CatGPT-Gateway, 2026-09-13; chat-on-steroids, 2026-08-30)* |
| `human turn` | `div[data-message-author-role="user"]` | the same; the text in `.whitespace-pre-wrap` | *reported (Clio, 2026-09-05)* |
| `assistant turn` | `div[data-message-author-role="assistant"]` | the same; the `<article data-turn>` wrapper is gone since 2026 — "zero `<article>` elements" in both snapshots; the text in `.markdown` | *reported (Clio, 2026-09-05)* |
| `interim assistant messages` | nothing — one reply is one message | "one logical turn routinely exposes several assistant-authored messages: interim commentary while it works, then the answer"; a visibly final response has been seen (2026-08-25) to lose its end-of-turn bit | *reported (chat-on-steroids, 2026-08-30)* |
| `paste over the threshold` | an insertion that takes the composer past 10,000 characters becomes an attachment chip outside the composer, with a **Show in text field** control that puts the text back into the composer | "If you paste more than 10k characters into the composer, ChatGPT will automatically convert the content into an attachment instead of inserting it directly into the text field"; "You can still move the content back into the message at any time by clicking on **Show in text field**"; Plus, Pro and Business first (at 5k, then 10k), Free and Go on 2026-06-22, Enterprise and Edu on 2026-08-04. Whether text the browser protocol inserts counts as a paste: nobody has looked | *reported (OpenAI 6825453, 2026-06-22 and 2026-08-04)*; the trigger *unknown* |
| `upload target` | a hidden `input[type="file"]` behind `button[data-testid="composer-plus-btn"]`, `aria-label` **Add files and more** | the same; alternatives seen: `aria-label` **Attach files**, `input[data-testid="file-upload"]` | *reported (CatGPT-Gateway, 2026-09-13)* |
| `upload accepted` | a visible leaf element outside the composer containing the file name | not looked at | *unknown* |
| `rename affordance` | the chat's sidebar entry has an options button, `[data-testid="history-item-N-options"]` with N its position — served visible, not on hover — opening a menu with a `[role="menuitem"]` reading **Rename**, then `input[aria-label="Chat title"]`; Enter confirms, Escape cancels; the entry's `aria-label` becomes the new title | the same, tested 2026-05-26; the options button appears only on hover of the entry; the menu is Radix-based with dynamic ids; the menu also holds **Delete**, **Archive** and **Share** — "be precise"; an empty name may be rejected | *reported (chatgpt-bridge, 2026-05-26)* |
| `chat title` | the sidebar entry's `aria-label` and link text, `#history a[aria-label="<title>"]`; the document title | the same; whether the header title is click-to-rename: not found | *reported (chatgpt-bridge, 2026-05-26)*; the header *unknown* |
| `modal in the way` | nothing | not looked at | *unknown* |
| `JS dialog in the way` | nothing | not looked at | *unknown* |
| `rate limited` | nothing | text chat "unlimited" on every plan since 2026-08-06, "subject to abuse guardrails"; a `429` on rapid sending still reported by users of the page; the banner's wording not found | *reported (OpenAI 6825453, 2026-08-06)*; the signal *unknown* |
| `captcha or security challenge` | nothing | not looked at | *unknown* |
| `generation failed` | nothing | not looked at | *unknown* |
| `memory` | nothing — the mock remembers nothing between chats | memory is on by default and "may create new memories from chats that remain in your chat history, including older chats"; temporary chats "do not use existing memories or create new memories". A fact for the brief that migrates into ChatGPT, not a state of the page | *reported (OpenAI 8590148, 2026-09-13)* |

### Export

| State | Signal the mock serves | Reported signal | Mark |
| ----- | ---------------------- | --------------- | ---- |
| `settings` | the profile menu opens **Settings**; **Data controls** is an entry in it | "Open your profile menu. Select **Settings**. Select **Data controls**." | *reported (OpenAI 7260999, 2026-08-25)* |
| `export page` | the Data controls page, at a path the slice picks | the path — whether a page of its own or a dialog at a hash route — was not observed; the page holds the **Improve the model for everyone** toggle among others | *reported (OpenAI 8983077, 2026-09-10)* for the toggle; the path *unknown* |
| `export button` | a visible **Export** control under an **Export data** heading | "Under **Export data**, select **Export**." | *reported (OpenAI 7260999, 2026-08-25)* |
| `export confirmation` | a visible `[role="dialog"]` holding a **Confirm export** control | "On the confirmation screen, select **Confirm export**." The screen's own words are not documented | *reported (OpenAI 7260999, 2026-08-25)*; the words *unknown* |
| `export requested` | a `[role="status"]` that appears only once the ask has been counted and a link minted | "ChatGPT sends an email or SMS message when the export is ready. Exports can take up to 7 days to arrive." | *reported (OpenAI 7260999, 2026-08-25)* |
| `already requested` | nothing — the mock's export is ready at once, and a second ask adds a second link | "Wait for the existing request to finish before submitting another request. While it is processing, ChatGPT may show that an export has already been requested." | *reported (OpenAI 7260999, 2026-08-25)* |
| `download needs session` | the archive is served to the signed-in session and refused to anyone else; the listing of links is open to all | "Download the export while you are signed in to the same account that requested it." The email's control reads **Download data export** | *reported (OpenAI 7260999, 2026-08-25)* |
| `link expired` | nothing — a link lives until the process stops; a token nobody minted is `404` | "The download link expires 24 hours after you receive it." "If the link has expired, request a new export." | *reported (OpenAI 7260999, 2026-08-25)* |
| `export file name` | the slice's | not documented; community reports contradict each other | *unknown* |
| `no import` | — | "ChatGPT does not support fully merging accounts or moving conversations from one account's chat history into another account's chat history." Uploading `conversations.json` to a chat makes it a reference file and "does not add old conversations to your chat history" | *reported (OpenAI 9106926, 2026-09-13)* |

## Notes

Traces of runs against chatgpt.com go in [`spike/traces/`](spike/traces/), read end to end
before they are committed, and are cited by file and line (brief `04` §49). No message
content, no titles and no account identifiers belong in any of them (§10).

## Sources

| Short name | What | Address | Date |
| --- | --- | --- | --- |
| OpenAI 7260999 | "Exporting your ChatGPT history and data" | <https://help.openai.com/en/articles/7260999-how-do-i-export-my-chatgpt-history-and-data> | updated 2026-08-25, read 2026-09-13 |
| OpenAI 9106926 | "Transfer exported conversations between ChatGPT accounts" | <https://help.openai.com/en/articles/9106926-transfer-exported-conversations-between-chatgpt-accounts> | read 2026-09-13 |
| OpenAI 6825453 | "ChatGPT — Release Notes", entries of 2026-06-22, 2026-08-04 and 2026-08-06 | <https://help.openai.com/en/articles/6825453-chatgpt-release-notes> | entries dated as cited |
| OpenAI 7426629 | "Why can't I log in to ChatGPT?" | <https://help.openai.com/en/articles/7426629-why-cant-i-log-in-to-chatgpt> | read 2026-09-13 |
| OpenAI 8983077 | "Data Controls FAQ" | <https://help.openai.com/en/articles/8983077-what-are-the-data-controls-settings> | updated 2026-09-10, read 2026-09-13 |
| OpenAI 8590148 | "Memory FAQ" | <https://help.openai.com/en/articles/8590148> | read 2026-09-13 |
| CatGPT-Gateway | `src/selectors.py`, ordered fallback chains for the page's controls | <https://github.com/GautamVhavle/CatGPT-Gateway/blob/main/src/selectors.py> | read 2026-09-13 |
| Clio | `extensions/src/selectors-chatgpt.js`, verified against saved DOM snapshots | <https://github.com/martymcenroe/Clio/blob/main/extensions/src/selectors-chatgpt.js> | verified 2026-05-23, re-verified 2026-09-05 |
| chatgpt-bridge | `harnesses/chatgpt-conversation-management.md`, the rename flow | <https://github.com/Dworrall21/chatgpt-bridge/blob/main/harnesses/chatgpt-conversation-management.md> | last mapped 2026-05-26 |
| chat-on-steroids | `docs/chatgpt-turn-signals.md`, how a finished turn is told | <https://github.com/totec448-spec/chat-on-steroids/blob/main/docs/chatgpt-turn-signals.md> | recorded 2026-08-30 |
| webgpt2mcp #4 | the composer's id gone after the redesign | <https://github.com/banddude/webgpt2mcp/issues/4> | 2026-09-05 |
| crapscraper #210 | a composer fallback chain including a Lexical root | <https://github.com/moja72/crapscraper/pull/210> | 2026-09-05 |
