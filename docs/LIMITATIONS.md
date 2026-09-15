# Limitations

**Kind:** Running record of what this migration cannot reproduce. Seeded by
[`10`](../specs/impl/10-attach-spike.md), added to by every slice that finds another one,
and quoted by [`21`](../specs/impl/21-scale-up.md)'s sign-off.
**Spike run:** none.

[§15](../specs/01-initial-brief.md) sets two fidelity targets and says which one wins:
semantic usability over "perfect reproduction of internal Claude metadata that cannot be
controlled through the UI". This file is the list of that metadata — everything §15 asks
for that the destination account will not hold after a migration, and what the operator
gets instead.

It is also where every *other* limitation this build has reported ends up, so that there
is one place to read before relying on any of it: what a store does not promise (`30`),
what one press in a source account does not promise (`31`), what an unattended run cannot
sign into (`24`), what a green `doctor` line about the agent is worth (`09`), and what a
passed rehearsal is not evidence of (`26`–`29`). Those sections were gathered here from
the slices' *Risks* and the pull requests that reported them; a limitation named in a
slice and nowhere else is one nobody reads before a run.

Every entry carries a mark:

- *by construction* — it follows from the approach itself (a conversation is replayed as
  one or more human messages pasted into a new chat), not from anything about the UI. No
  observation can change it; only a different approach could.
- *observed on `<date>`* — a human watched the UI refuse or ignore it.
- *unknown* — expected to be a limitation, not yet confirmed. `10` confirms these.

## Structural fidelity (§15)

### Message-level metadata

- **Original message timestamps.** Every migrated message is timestamped when it is
  pasted, not when it was written. The composer offers no way to set a send time. The
  original times survive only inside the seed text, where `04` renders them as part of the
  transcript. `17` records this against every chat that lands, as the per-conversation
  limitation `timestamps_not_preserved`, so that `19`'s account of one conversation is
  complete without this file. *by construction*
- **Message identifiers.** The destination account mints its own message ids. The source
  export's ids are not carried over and cannot be referenced from the destination.
  *by construction*
- **Per-message boundaries.** A source conversation of forty turns becomes one human
  message per seed part, not forty messages. `state.json` records how many parts a
  conversation became; the turn structure itself lives in the rendered text.
  *by construction*
- **Message roles.** Every migrated turn is inside a human message regardless of who said
  it in the source. The seed labels each turn, so the roles are readable but not
  structural. *by construction*
- **The model that produced each assistant turn.** The export records a model per
  conversation at best; the UI has no way to attribute a pasted turn to a model, and the
  acknowledgement Claude writes back comes from whatever model the destination account is
  set to. *by construction*

### Conversation-level metadata

- **Conversation creation and update times.** A migrated chat is created now. Whether the
  UI exposes any way to influence either is unknown until `10` looks. *unknown*
- **Conversation identifiers.** The destination mints a new `/chat/<uuid>`; `06`'s
  `state.json` maps source id to destination id, which is the only place the two are tied
  together. *by construction*
- **Titles.** `17` renames the chat through the UI — Hermes opens the chat's own menu and
  types the source title, capped at `fidelity.title_max_chars` — and then checks the
  displayed title from the page. Whether that affordance exists and is reliable is `10`'s
  Q7, still unanswered, so the step is best effort by design: a chat whose title did not
  take is recorded as `title_not_set` against that conversation and migrated all the same,
  and an operator who finds the rename unreliable sets `fidelity.rename_title = false` and
  gets `title_not_set` for every conversation. Where the title is not set, "equivalent
  titles" is met only by the header line `04` writes into the first seed part, which names
  the source conversation inside the chat's first message. *unknown*
- **Chronological order between conversations.** Conversations are migrated in the order
  `12` picks, so the destination's sidebar order reflects the migration, not the source
  history. *by construction*
- **Stars, archive state, folders and projects.** Not part of `02`'s export model and not
  set by any slice. *unknown*

### Content

- **Attachments whose bytes the export does not carry.** `03` classifies these; `16`
  uploads the ones we have and records the rest. Whether the real export archive contains
  bytes at all is an open question in [`specs/README.md`](../specs/README.md). *unknown*
- **Which message an uploaded attachment hangs off.** An attachment chip belongs to the
  message being composed, so every file `16` uploads is attached to the first message of
  the migrated chat rather than to the message that carried it in the source. The seed's
  `[File: … — attached to this chat]` line, written where the original message was, is
  what ties the two back together. *by construction*
- **Rendered artifacts, tool calls and code execution results.** What the export holds for
  these, and what survives being pasted as text, is not yet known. *unknown*

## The names `19` prints

Every limitation the report counts is one of these six slugs, recorded against a
conversation in `state.json` and printed by name in the `Limitations:` block. The first
four are `04`'s, written when the seed is rendered and carrying the number of blocks they
stand for (`thinking_omitted:3`); the last two are `17`'s, written against a chat that was
read back. `19` counts conversations rather than occurrences, so the per-conversation
number stays in `state.json` where the conversation it belongs to is.

[`21`](../specs/impl/21-scale-up.md) gives each one a heading of its own, a count from the
full run and a kind:

- **UI limit** — the Claude web interface offers no way to do it. A different tool driving
  the same UI would hit the same wall.
- **export limit** — the export does not carry what would be needed. A richer export could
  lift it.
- **tool choice** — this build decided not to. A later slice could decide otherwise, and
  the entry says what that would cost.

A count is a measurement, so it carries the experiment marks — `*not yet run*` until the
full run produces it, `*measured on <date>*` after — rather than the three marks the
observations above use. `tests/test_scale_up_doc.py` checks that every name the code can
print has a heading here, and that each heading carries a count and a kind.

### `branches_dropped`

The export's off-path messages, left out of the seed. A conversation that was edited and
re-answered is migrated as the path the export marks current; the other branches are
counted and not rendered. Replaying them would mean editing a message in the destination
chat and answering it again, which is a second migration of the same conversation.

| Conversations in the full run | Kind | Mark |
| --- | --- | --- |
| — | tool choice | *not yet run* |

### `thinking_omitted`

Extended-thinking blocks. They are not part of what the person saw, and nothing in the
composer can produce one.

| Conversations in the full run | Kind | Mark |
| --- | --- | --- |
| — | UI limit | *not yet run* |

### `tool_calls_summarised`

A tool call the seed renders as `[Tool call: name]`. The call itself cannot be replayed
into a new chat: the destination would have to run the tool, which is a different action
in a different account.

| Conversations in the full run | Kind | Mark |
| --- | --- | --- |
| — | UI limit | *not yet run* |

### `unknown_blocks`

A content block this build has no rendering for, kept as `[Unsupported content: type]` so
that a reader of the migrated chat knows something was there. What the block held is in
the export; what to do with it is `02`'s to decide, one block type at a time.

| Conversations in the full run | Kind | Mark |
| --- | --- | --- |
| — | tool choice | *not yet run* |

### `timestamps_not_preserved`

*Original message timestamps*, above, recorded against every chat that lands. The composer
offers no way to set a send time, so every migrated message is stamped when it was pasted.
Expected against every completed conversation; a count below that is a finding about `17`
rather than about the UI.

| Conversations in the full run | Kind | Mark |
| --- | --- | --- |
| — | UI limit | *not yet run* |

### `title_not_set`

*Titles*, above: the chat kept the destination's own title because the rename did not take,
or because `fidelity.rename_title` is off. A UI limit in the first case and a tool choice
in the second, and the count does not distinguish them — the configuration that produced
the run does.

| Conversations in the full run | Kind | Mark |
| --- | --- | --- |
| — | UI limit | *not yet run* |

## Semantic fidelity (§15)

Not a limitation list — the target. `20` measures it with the six §18 questions and,
optionally, the `judge` extra. Anything it finds that the UI cannot be made to do lands
here.

## The agent (`09`)

What installing a skill into a Hermes profile does and does not prove. Neither entry is
about fidelity; both are about what `doctor`'s green line is worth.

- **Nothing tells Hermes where its home is.** `hermes.home` is *our* view of the profile
  tree — the one `setup` writes into and `doctor` looks in. The subprocess environment is
  built from scratch (`09` forwards `PATH`, `HOME` and `LANG` and nothing else), so it
  carries no Hermes-home variable, and an operator's own is stripped rather than passed.
  For the `~/.hermes` default the two agree, because `HOME` is forwarded; an operator who
  overrides `hermes.home` to a tree the `hermes` on `PATH` does not use gets
  `skill installed ok` confirming our own write. *by construction*
- **Whether Hermes can be told a home at all** — and so whether the override could be
  propagated rather than narrowed — is a question about an external tool's interface that
  `09` refused to guess at, for the same reason `MINIMUM_VERSION` is `0.1.0`. `10`
  installs a real Hermes and settles it. *unknown*

## The spike harness (`10`)

- **The paste ladder measures one round per unattended invocation.** Nothing in `08`
  clears a composer — no helper does, and the slice that would add one is somebody
  else's — so between rungs only a person can, and a `--no-prompt` run that asks for more
  gets one usable row and `composer_not_empty` for the rest. The flag says so in its help
  and warns when asked for more than one round; a full ladder is a human at the keyboard.
  Reported by `18` rather than built, because the fix is a new helper in `src/`. *by
  construction*

## The rehearsal (`26`–`29`)

What a passed rehearsal is not evidence of. The record itself
([`rehearsal-01.md`](rehearsal-01.md)) says the first of these every time it is written;
the three are here because `21`'s sign-off quotes this file and not that one.

- **A rehearsal can only find what the mock can show.** The failure states §21 lists are
  the ones a migration is most likely to meet on the real site, and `26`–`29` serve none
  of them: a rate limit, a login expiry mid-run, a modal or JavaScript dialog, a
  generation error, a CAPTCHA, and a code prompt at sign-in. A rehearsal that passes says
  the protocol runs end to end against a site that behaves; it says nothing about the
  six. *by construction*
- **A rehearsal is not evidence about claude.ai.** Every `*unknown*` in
  [`claude-ui-map.md`](claude-ui-map.md) is still `*unknown*` afterwards, semantic
  fidelity is *not applicable* rather than passed, and whether a model can follow the
  skill is the pilot's question (§27). The mock is governed by the UI map, so it can only
  ever reflect what the map already claims. *by construction*
- **The drill leaves an orphan chat.** A one-shot agent reports the chat's id when it
  returns, so a run killed before it returns leaves a chat the tool never learned about,
  and the retry starts another. The mock's ledger is what makes it visible — the tool's
  own drill instrument cannot see it — and `29`'s record names it. A property of the
  design rather than a defect in it, and the same property a killed *real* run has.
  *by construction*

## Unattended runs (`24`)

- **No unattended Claude sign-in.** Claude signs in with an emailed link behind an
  attestation (brief 07, [ADR 0008](adr/0008-the-sign-in-stays-in-the-browser.md)), and
  neither half of that is a thing the tool does: nothing here reads a mailbox or solves a
  challenge, and nothing will. `login --non-interactive` — with or without `--link` — is
  exit `2` and names the command a person runs; a run that finds its Claude session expired
  is exit `3` (or a pause and exit `5` mid-run) and names `login`. The destination is a
  Claude account, so this is the destination's rule too (§75). *by construction*
- **The ChatGPT walk is password sign-in only.** ChatGPT's unattended sign-in types an
  email address and a password (`44`). An account whose sign-in is an emailed code, a
  passkey, Google or Apple, or which meets a CAPTCHA or a security challenge, cannot be
  signed in without a person: exit `3` with the `login` instruction. *by construction*

## The sign-in by link (`50`, `53`)

What §73's two commands do not promise.

- **Whether a pending sign-in survives the window closing is unknown.** `login` keeps its
  window open until the link is spent so as not to depend on it. `login --link` with no
  window open launches the profile and tries; that works only if the cookie the pending
  sign-in lives in outlived Chrome, which nobody has read off the page. When it did not,
  the tab lands back on the code prompt and the tool says so: `the link led to a code
  prompt — the pending sign-in is not in this profile`. *unknown*
- **What the link shows when opened elsewhere has not been seen.** The page's own words
  say a link opened where the pending sign-in is not shows a *code* rather than signing in
  (`docs/claude-ui-map.md`, `link opened elsewhere`); what that page looks like, and
  whether the tab comes back to `/login`, is unobserved. So the code-prompt refusal fires
  on the one shape the tool knows, and everything else — expired, already spent, a page
  nobody has described — is `the link was not accepted` after `timeouts.signin_s`. The
  code itself is a door the tool does not have yet (§80). *unknown*
- **Two terminals, one browser.** `login --link` adopts whatever browser is on the
  profile's port and navigates its first tab on the site. That is `login`'s window by
  design; a `login --link` run while an `extract` is mid-ask in the same profile navigates
  the ask's tab away, because a marker cannot say which command launched Chrome. One
  browser at a time is the rule (`31`), and this is one more reason for it. *by
  construction*
- **The sign-in link's host is not pinned**, as the export link's is not: `https` is the
  whole check, and a link that signs in somebody else's account signs this profile in as
  them. The label is the operator's word. *by construction*
- **`login --link` needs a display.** The vendor's bot management refuses a headless Chrome
  (below, *The ask*), so the link is always spent headed; a window opens and closes, or
  `login`'s own window is used. *observed on 2026-09-15*
- **A link that hops through another host** — a mail provider's click tracking — takes the
  tab off claude.ai for a moment. `login`'s wait never opens a tab, so that moment costs a
  poll and nothing else; whether real sign-in links do hop is unknown. *unknown*

## The store (`30`)

Two things to know before relying on a store. Neither is about fidelity, which is what
the rest of this file is about; both are about what a backup does *not* promise.

- **An unfinished snapshot has to be removed by hand.** A fetch that dies partway through
  the copy leaves a stamp directory with no `COMPLETE` in it, which is exactly how an
  unfinished snapshot is meant to look — but the next fetch under the same ask computes
  the same stamp and is refused, because §33 says the store never overwrites. The tool
  deletes nothing from the store, so the refusal names the directory and an operator
  removes it. `snapshots` shows such a row as `incomplete`. *by construction*
- **The link's host is not pinned, so the label is the operator's word.** A vendor emails
  a signed URL on a storage host nobody can predict, so the fetch checks the scheme and
  then the content — is this a zip, is it an export of this source — and never the host.
  A link that leads to a valid export of somebody *else's* account would be filed, under
  whatever `--account` said. The label is the operator's claim about whose account it is,
  and the tool cannot check it. *by construction*
- **A filing costs twice the archive's bytes and two passes over them.** The fetch writes
  a temporary file, verifies it, then copies it into the stamp directory, hashing as it
  goes; both files exist at once and the bytes are read through twice. A multi-gigabyte
  export is minutes rather than hours, and `store.max_download_bytes` (5 GB) is the
  ceiling that keeps a fetch bounded — but a disk with room for one copy is not a disk
  with room to file it. *by construction*

## The ask (`31`)

What one press in a source account does not promise. All three are about the vendor's
page, which nobody has watched yet: `docs/extraction-01.md` is where they stop being
`*unknown*`.

- **A rate limit on asking is indistinguishable from a page we do not recognise.** Claude
  may refuse a second export request within some window, and what the tool would see is
  the same thing it sees when the page has changed: no confirmation inside
  `timeouts.ask_s`. It exits `1` with `no confirmation that the export was requested`,
  writes no `ask.json`, and leaves a person to read the page. Erring this way is
  deliberate — a record claiming an export was requested is worse than one saying nobody
  can tell — but it means "asked too soon" and "the button moved" arrive as one message.
  *unknown*
- **A JavaScript dialog on the export page stops the ask.** It is never answered: what it
  asks is unknown, and the ask is allowed one action in the account. Exit `1`, no record,
  and a person clears it. *by construction*
- **One browser at a time.** The destination session and each source session share
  `browser.cdp_port`, so a Chrome left running for one is `PortInUseError` for the
  other. Close it and run the command again; sessions are sequential by design, not by
  accident.
  *by construction*
- **An unattended ask on a signed-out Claude profile stops.** There is no unattended Claude
  sign-in (above), so a cron job whose source session has expired exits `3` and names
  `login` with the account's flags — the right failure, but a silent one until somebody
  reads the log. A signed-in profile needs no model at all, which is the case the backup is
  built for. *by construction*
- **The ask cannot run headless against claude.ai.** Measured 2026-09-15 on a signed-in
  profile, Chrome 152: `--headless=new` is served a Cloudflare interstitial at the export
  page — `challenges.cloudflare.com`, a `ray-id` footer, forty-seven nodes — which never
  resolves, while the same profile headed renders the panel in about 2.9 s. So
  `--non-interactive` extraction of a Claude account is refused by the vendor's bot
  management, not by anything in this tool, and the ask reports the panel never appeared
  and names dropping the flag (`62`). Clearing that check is the one thing this tool will
  not learn to do ([ADR 0008](adr/0008-the-sign-in-stays-in-the-browser.md)); a cron job
  that needs a Claude export needs a display. Whether the **fetch** is refused the same way
  is not yet known: it downloads from a signed URL on another host, and the link that would
  answer it expires before anyone can plan around it. *observed on 2026-09-15*

## The ChatGPT source (`43`–`45`)

What extraction from a ChatGPT account does not promise. Nobody has watched chatgpt.com
or read a real ChatGPT export; every row the source stands on is *reported* or *unknown*
in `docs/chatgpt-ui-map.md` and every claim about the archive is *assumed* in
`docs/chatgpt-export-format.md`. `docs/extraction-02.md` is where they stop being so.

- **The auth host's screens are the mock's.** The walk expects a **Log in** on the landing
  page, an email step and a password step on `auth.openai.com`, each submitted with Enter.
  A code prompt, a CAPTCHA, a banner or a different host stops the unattended sign-in with
  exit `3` and the `login` instruction, and a sketch of what it saw in the trace. *unknown*
- **The Data controls path is one string.** The tool navigates straight to
  `/settings/data-controls`; the site may serve the page elsewhere, or as a dialog. A wrong
  path is exit `1` with `export button not found`, and one edit to correct. *unknown*
- **Whether the real link needs the session at all.** The fetch opens the source session's
  browser because OpenAI's documentation says the download must be made signed in; a real
  link that a browserless fetch could have taken would make that a cost and not a need,
  and `fetch_needs_session` is the one flag that would change. *unknown*
- **The zip's file name is never kept.** The trace carries its length and suffix; the file
  is named by its download guid. What the vendor calls it is not known. *unknown*
- **The 24-hour expiry, "already requested" and a rate limit on asking** are answered by
  the site's page and not by the tool: a dead link is `link refused: HTTP <code>` or `the
  link led to a page`, an ask the site declines is `no confirmation that the export was
  requested`, exit `1`, no record. *unknown*
- **A ChatGPT snapshot cannot be restored by this build.** `import` and `inspect` refuse it
  with ADR 0005's reason: each source needs its own importer, and a snapshot of a source
  the tool cannot import is still a backup. *by construction*
- **The fetch opens a browser.** It obeys "one browser at a time" and needs the session
  signed in — interactively a person, unattended the credentials. A cron job that fetches
  needs `DATAPORTER_AUTH__EMAIL` and `DATAPORTER_AUTH__PASSWORD` in its environment for the
  case the session has expired. *by construction*
- **Composer drift is a signed-out root.** `probe.logged_in` on chatgpt.com's root depends
  on the composer selector matching the site's redesigned composer, the highest-risk
  *reported* row of the map; a signed-in root without a match reads as signed out, the walk
  finds no **Log in**, and the run stops with `authentication required`. *unknown*
- **A file the mock accepted is a gap; a real export's files may not be.** The 2026 export
  is reported to carry attachment bytes as `file_<id>.dat` members; the snapshot counts
  them as `Files:` and lists only the referenced ones no member carries. Confirming it is
  the first thing reading a real export settles. *unknown*

## How to add to this file

One bullet, one mark, and the slice that found it. A limitation discovered without a mark
is an impression; `tests/test_spike_docs.py` fails the build for an unmarked entry.

A limitation the *report* can print is not a bullet but a heading of its own under
*The names `19` prints*, with a count and a kind, because `21`'s sign-off quotes it by
name: add the slug to the code and `tests/test_scale_up_doc.py` fails until the heading
exists.
