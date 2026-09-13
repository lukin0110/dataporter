# 34 — The sketch

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 04](../04-trace.md) §45, §46 (the label rule), §50
**Depends on:** [33](33-trace-and-move.md), [07](07-browser-session.md) (the CDP page)
**Enables:** [35](35-watch.md) (which takes sketches too), [37](37-traces-as-evidence.md)
**Status:** Done

## Goal

The page in outline, taken from the accessibility tree, with a label for every control
and only a shape for everything else; written once per distinct page and named by its
hash after; and attached to every move as what the page showed before and after it. It
is what turns "composer_present: false" into something a person can fix the mock with,
and it carries no message, title or address by construction, which a seeded page proves.

## In scope

- **The roles** (`browser/sketch.py`, new):

  ```python
  LABELLED_ROLES = ("button", "textbox", "searchbox", "combobox", "checkbox", "radio", "switch",
                    "menuitem", "menuitemcheckbox", "menuitemradio", "tab",
                    "dialog", "alertdialog", "alert", "status", "progressbar")
  SHAPED_ROLES = ("heading", "link", "list", "listitem", "image", "table",
                  "main", "navigation", "banner", "contentinfo", "complementary", "region",
                  "article", "form")
  LABEL_LIMIT = 80
  ```

  A node whose role is in neither is skipped; its children are still walked. Roles are
  the accessibility tree's own names as CDP reports them — `image`, not `img`, which is
  what reality corrected this list's first draft to.
- **Taking one**: `take(page: cdp.Page, site: Site) -> Sketch`. `Accessibility.enable`
  on every take — idempotent, and cheaper than tracking it per connection — then
  `Accessibility.getFullAXTree`; nodes in the order returned,
  which is document order; `ignored` nodes skipped. For a labelled role: `role`,
  `label` = the node's `name.value` through `log.safe_token(value, LABEL_LIMIT)`,
  `disabled: true` only when the `disabled` property is true, and for `textbox` and
  `searchbox` `chars` = the length of `value.value`, never the value. For a shaped role:
  `role`, `chars` = the length of the name, `hash` = the first twelve hex digits of the
  SHA-256 of the name; a run of consecutive shaped nodes with the same role collapses to
  `{"role", "count", "chars"}` with `chars` summed and no hash. `selectors` is one
  `Runtime.evaluate` tagged `dataporter:selectors`, built from `site.selectors`, returning
  `document.querySelectorAll(selector).length` per name, in the site's order — a count of
  what is there, visible or not. `dialogs` is `probe.pending_dialogs(page)`. `path` and
  `query` are `trace.url_fields(page.url)`. `title_chars` is the length of the root
  node's name, which is the document's title. The line, keys in this order:

  ```text
  {"kind":"sketch","ts":"…","t_ms":640,"hash":"3f9c2a1b7e04","path":"/new","query":[],"title_chars":8,"controls":[{"role":"textbox","label":"Write your prompt to Claude","chars":0},{"role":"button","label":"Send message","disabled":true},{"role":"link","count":12,"chars":231}],"selectors":{"COMPOSER_SELECTOR":1,"MESSAGE_SELECTOR":0,"TITLE_SELECTOR":0,"FILE_INPUT_SELECTOR":1},"dialogs":[]}
  ```

  `hash` is the first twelve hex digits of the SHA-256 of
  `json.dumps(fields, sort_keys=True, separators=(",", ":"))` over every key but `kind`,
  `ts`, `t_ms` and `hash` itself. `Sketch` is a frozen pydantic model with `extra="forbid"`
  and `hash` a property, so that it is never a field a line could carry twice.
- **Once per page** (`trace.py`): `Trace.sketch(sketch) -> str` appends the line when its
  hash is new to this trace and returns the hash either way. `Trace.open` starts with no
  hashes; `Trace.attached` reads the file's existing `sketch` lines' hashes on open, so a
  helper process knows what the run has already drawn — and `trace.current()` now keeps
  the trace it attached to, per path, so a helper's two sketches and its move share one
  descriptor and one read of the file (`trace.reset()` forgets it, for tests).
- **Before and after** (`helpers.driving`, `helpers.sketch_of`, `helpers.run`,
  `export_page._click`): `Surface` gains `site: Site | None` — `CLAUDE` carries
  `probe.MIGRATION_SITE`, `EXTRACTION_SURFACE` its `EXTRACTION_SITE`, `LOGIN_SURFACE` the
  migration selectors plus the form's two, and the test suite's fixture surfaces none,
  which sketches with an empty table. `sketch_of(page, surface)` is the one call: no
  trace current, no sketch and no CDP call; a tree the browser refuses is a warning and
  `None`. `driving()` takes one after its guard and attach, before it yields, and another
  in its `finally` after the body, and leaves the pair in a `contextvars.ContextVar`
  (`_SKETCHED`); `run` resets the pair before `work` and reads it after, and writes the
  hashes as the move's `before` and `after`. A helper that never enters `driving` —
  `no_claude_tab`, `ambiguous_tab` — leaves both `null`. `export_page._click` holds its
  page and takes its own pair around the click. The sketch is taken on the connection the
  helper already holds: no second attach.
- **Where a sketch may look**: anywhere the tab is. The sketch sends no input and
  navigates nowhere; the surface (ADR 0001) is a rule about hands, and `driving` has
  already applied it before the first sketch is taken. What a sketch of an off-surface
  page would show is exactly the evidence the UI map's `signed out` row wants.
- **Tests**:
  - `tests/test_sketch.py` — a hand-built AX tree → the line above, key for key; a
    link, a heading, a list item, an image and a landmark keep no label; a run of twelve
    links collapses to one entry with the summed `chars`, and a control between two
    links breaks the run; a textbox reports `chars` of its value and never the value; a
    `disabled` button says so and an enabled one says nothing; a label is bounded and
    cannot forge a line; ignored and unknown nodes are skipped; the hash is stable and
    changes with a label; a second `sketch()` of the same hash writes nothing and returns
    the hash; `attached` knows the file's hashes and skips lines it cannot read; `take`
    against the fake Chrome reads the tree, the counts and the URL, and a count that is
    not a number is `0`; a tree the browser refuses leaves the move with `null` sketches
    and the helper's answer unchanged; `current()` attaches once per path.
  - `tests/test_browser_helpers.py` — every helper's move carries `before` and `after`
    from `driving`'s pair, `null` when the tab was never found; the two export clicks
    carry theirs.
  - `tests/fake_chrome.py` — answers `Accessibility.enable` and
    `Accessibility.getFullAXTree` with a tree the test configures (`FakeTarget.ax_tree`),
    and records both like every other method; `fake_composer.FakePage` and
    `fake_export_page.FakeExportPage` answer the `dataporter:selectors` expression from
    what they hold; `conftest.py` resets the process's trace around every test.
  - Live tier, `tests/fixtures/pages/leaky.html` and `tests/test_sketch.py`'s
    `requires_a_browser` case — a page seeded with a chat title in an `h1`, an email
    address in a paragraph, a message body under `[data-testid="assistant-message"]`,
    twelve sidebar links each titled after a conversation, a `contenteditable` holding a
    seed, and a URL with `?token=abc123`: the sketch's line, and the whole trace file the
    move lands in, contain none of those byte strings; and the same page's controls
    (`Send message`, `Write your prompt to Claude`, `Accept all`) are all there, the
    twelve links are one run, the query is `["token"]`, and the five selectors count what
    the markup holds. A second live case sketches `new.html` and checks its five counts.
- **Docs**: `README.md`'s trace paragraph (what a sketch keeps and what it does not);
  `docs/claude-ui-map.md` (one sentence under the table: the `selectors` object of a
  sketch is the map's middle column, counted on a real page).

## Out of scope

- A sketch on a navigation or a dialog, without a move: [35](35-watch.md).
- Screenshots beside a sketch: brief §51.
- The full accessibility tree, or any DOM: never (§45); Hermes's own transcripts hold
  page snapshots for anyone who needs one (`specs/README.md`, output discipline).

## Design notes

- **The accessibility tree, not the DOM.** It is already the page as a person meets it:
  roles and names, no markup, no styling, and the one place where "what would a person
  read on this control" has a definition (the accessible name). Hermes's own
  `browser_snapshot` is the same tree, so what the tool sketches is what the agent saw.
  Rejected: `DOM.getDocument` with a depth (a markup dump the label rule would have to
  be re-derived on, tag by tag); a screenshot (content by definition, and not diffable).
- **Labels for controls, shape for the rest.** A control's name is the site's chrome and
  is what the mock has to reproduce; a link's name is a conversation's title, a heading's
  is one too, a list item's is a message, and an image's alt text is anyone's guess. The
  line is drawn on the role and not on the text, so it cannot be argued with one label
  at a time. Rejected: an allow-list of known labels (the trace exists to learn labels
  nobody knows yet); a deny-list of patterns (an email regex catches an email and nothing
  else).
- **A hash of the name where the name is withheld.** A reader can still tell "the same
  heading as before" from "a different one" and count how many distinct links a sidebar
  holds, without a word of either. Twelve hex digits is enough to tell apart and too few
  to invert by table. Rejected: no hash (a sketch could not say whether a rename took);
  the full digest (sixty-four characters twelve times per sidebar).
- **`selectors` counts, it does not judge.** The middle column of the UI map is a list of
  selectors nobody has tested on the real page; the honest report is how many elements
  each finds, visible or not, and the probe's own visible-and-enabled judgement is
  already in the move's `result`. Rejected: the visible count only (a hidden twin, as the
  export page's fixture has, would then be invisible to the very file meant to find it).
- **Taken in `driving`, on the helper's connection.** `run` has the client and not the
  page; `driving` has the page and is the one choke point every hand passes through, so
  the pair is taken there and handed to `run` through a context variable rather than a
  new return type. Rejected: a second attach from `run` (a second WebSocket per helper
  call, and a tab to pick again); changing `driving`'s signature (every helper and both
  extraction modules call it).
- **A sketch may look off the surface.** ADR 0001's wall is on driving, and the sketch
  drives nothing: it reads a tree and counts selectors. The `signed out` row is the one
  the mock has the least evidence for, and a sketch that refused to look at `/login`
  would keep it that way. Rejected: refusing off-surface sketches (safe against nothing
  and blind to the most-wanted page).

## Acceptance criteria

- `make check` is green, and `tests/test_sketch.py` covers every branch of `take`
  against hand-built trees.
- `take` of the hand-built tree in the tests yields the block above, byte for byte, and
  its hash is stable across two calls a second apart.
- A trace of a rehearsal's `import --pilot` holds one `sketch` line per distinct page
  and a `before`/`after` hash on every move, and every hash a move cites appears on an
  earlier `sketch` line of the same file.
- *(Live: it needs a real Chromium.)* Against `leaky.html`, the trace file left by one
  `browser probe` contains none of the seeded strings and all three control labels.
- *(Live: the same.)* Against `tests/fixtures/pages/`, every `selectors` count on
  `new.html` equals what the page's markup holds — one composer, one file input, no
  message.

Every criterion above was met on 2026-09-13: the first three by the suite against the
fakes, and the two live ones against a real Google Chrome 152 on macOS, driven by
`tests/live_browser.py`. The sketch of `leaky.html` kept the three control labels and
the twelve links as one run of 219 characters, counted the five selectors as the
markup holds them, carried `["token"]` for the query, and neither its line nor the trace
the probe's move landed in held any of the nine seeded strings; `new.html` counted one
composer, one file input and nothing else. `sketch.py` is at 100% and the gate held at
99.54% over 1808 tests. The status is `Done` for `32`'s reason: the live criteria need a real Chromium
and no account, and one has walked the pages.

## Risks

- **The name of a control can be content.** A button labelled with a conversation's
  title — "Rename 'My trip'" — is a control with content in its name. `safe_token` and
  the limit bound the damage; the live test seeds no such button because the fixture
  pages have none, and the first real trace is read end to end before it is committed
  (§49). If the real site has one, the role rule gains an exception, in this slice.
- **`getFullAXTree` on a long chat is large.** Hundreds of nodes per message; a chat of a
  thousand messages is a tree of tens of thousands, walked once per move. The walk is
  linear and the line written is not, but a helper's `elapsed_ms` will show it; a depth
  limit or `Accessibility.getPartialAXTree` on the composer's ancestors is the fallback
  and needs no format change.
- **Reading the file's hashes on every helper call.** A full run's trace can reach
  megabytes and a helper process scans it on attach. A pilot's does not, and the pilot
  is what Claude Code reads; if a full run's cost shows, the hashes get a sidecar.
