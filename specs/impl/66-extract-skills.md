# 66 — `extract-skills`

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 09](../09-skills.md) §88, §89, §90, §91, §92, §93, §94, §95; amends
[Brief 03](../03-extraction-and-backup.md) §32, §33 and §36
**Depends on:** [31](31-source-session-and-ask.md), [45](45-fetch-through-the-session.md),
[60](60-download-progress.md), [63](63-everything-but-the-logs.md)
**Enables:** [67](67-the-mock-grows-skills.md)
**Status:** Built

## Goal

Add `dataporter extract-skills --source claude --account work [--stamp S]`: read the
account's own skills from claude.ai, file each one into a snapshot's `skills/` directory
exactly as the vendor served it, and record what did not come back. The command clicks
nothing in the source account. The mock's side of it, and the rehearsal, are [`67`](67-the-mock-grows-skills.md).

## In scope

- **`dataporter extract-skills`**, a top-level command beside `extract`. The first
  hyphenated top-level name — `browser await-response` and `browser close-extra-tabs` are
  the only hyphenated ones today and both are subcommands — so it is declared with an
  explicit string, `@app.command("extract-skills")`, as `@app.command("import")` is.
- **`--account LABEL`, required**, and **`--source SRC`** defaulting through
  `Settings.source`, both declared with the existing `Account` and `Source` annotations and
  resolved by `config.with_account`, exactly as `logout`'s are (`63`).
- **`--store DIR`**, the shared `StoreDir` option, as `extract` and `snapshots` carry it:
  the skills file into the store, so the command names where. Documented in the README's
  command row beside the other three.
- **`--stamp STAMP`**, optional, a new `Stamp` annotation with no literal default. It is
  validated with the existing `store.parse_stamp` **in the library, not the CLI** — the
  command body stays branch-free (`23`) — and a value that does not parse is a
  `UsageError`, exit `2`, raised before a browser is launched. That validation is also what
  keeps a directory name out of the caller's hands: `--stamp ../../x` does not parse.
- **`src/dataporter/extract_skills.py`**, the library operation:

  ```python
  def extract_skills_command(
      settings: Settings, request: SkillsRequest, *, sink: Sink = DISCARD
  ) -> SkillsOutcome: ...
  ```

  `SkillsRequest(stamp: str | None)` and `SkillsOutcome(..., exit_code: int)`, both frozen,
  as `23` has every operation. It is **not** under `src/dataporter/skills/`, which is the
  tool's own skill (ADR 0004) — see the glossary edit below.
- **`src/dataporter/browser/skills.py`**, the two reads. No selectors and no clicks:
  - `ORG_TAG` / `org_js(source)` — an in-page `fetch` of `Source.organizations_path`,
    returning the first organisation's uuid and nothing else.
  - `LIST_TAG` / `list_js(source)` — an in-page `fetch` of `Source.skills_list_path`,
    formatted with that uuid, returning one object per skill holding **only** `id`, `name`,
    `creator_type`, `enabled` and whether a `backing_plugin_id` is set. The description and
    the display name are left in the page: nothing needs them (§38).
  The address one skill is served from is `sites.skills_download_url(source, org,
  skill_id)`, in `browser/sites.py` beside the two walls — built from the `Source` and the
  listing's `id`, never from anything a response carried, and percent-encoding both so an
  id with URL syntax cannot change the request. `browser/skills.py` reads; `sites` spells
  the addresses.

  Both expressions are tag-dispatched the way `export_page`'s are, so a fake answers them
  by tag rather than by parsing JS. They are async IIFEs of their own rather than
  `probe.expression`'s — no prelude, since nothing here touches an element — and
  `Page.evaluate` already awaits the promise.
- **New `Source` fields**, beside `export_page_path`: `organizations_path`,
  `skills_list_path` and `skills_download_path`, with `Source.has_skills` true when the
  last two are set. Claude's, from the reading in
  [`claude-ui-map.md`](../../docs/claude-ui-map.md):

  ```python
  ORGANIZATIONS_PATH   = "/api/organizations"
  SKILLS_LIST_PATH     = "/api/organizations/{org}/skills/list-skills"
  SKILLS_DOWNLOAD_PATH = "/api/organizations/{org}/skills/download-dot-skill-file?skill_id={skill}"
  ```

  No `skills_page_path`: the page the skills are listed on is never navigated to (see
  *Design notes*), so a field for it would name something nothing reads.

  A source without them extracts no skills, and `extract-skills --source chatgpt` is a
  `UsageError`, exit `2`, naming the source.
- **The wall.** `sites.extraction_pattern` gains one door, the download address, and
  nothing else — not the list, not the page the skills are listed on. The list and the
  organisations read are in-page `fetch`es and never navigations, so they never reach
  `helpers.guard`; what keeps *them* on the surface is that their URLs are built from
  `Source` constants and from nothing a response carried. `tests/test_sources.py` pins the
  widened pattern byte for byte, as it pins today's.
- **The flow**, once per run: `launcher.launch` on the export page → `sign_in_to_source`,
  exactly as the ask does it → `bring_to_export_page` → under `helpers.driving`, `org_js`
  then `list_js`, each recorded as a move → filter → one `download.fetch` per kept skill →
  file → block → close. The browser is closed on every path, as `63`'s is, so the cookie
  jar flushes. The reads are made **on the export page**: the one page inside the wall
  that is a page, already sketched by every ask, and one whose controls carry no skill's
  name.
- **The filter**: keep `creator_type == "user"`. A `creator_type` the code does not know is
  **not** kept — an unknown value is somebody else's skill until a person says otherwise.
  `enabled` and plugin membership are recorded and never filtered on (§90).
- **`download.fetch` is reused unchanged**, once per skill, `into` the account home's `tmp/`
  as `45`'s fetch does. Each landing calls `extract.landed(...)` so §60's line is the same
  line:

  ```text
  downloaded  research-helper.skill  4.1 KB
  ```

  Four of `extract`'s helpers are promoted to do it — `landed`, `display_of`,
  `sign_in_to_source`, `digest_of` — and `export_page.bring_to_export_page` with them,
  because `ruff`'s `PLC2701` refuses an underscored import across modules and a second
  spelling of any of them would be a second thing to keep in step.
- **Filing.** A new `Store` method files the skills directory: take the append's lock —
  `APPENDING`, created `O_CREAT | O_EXCL`, so a second append to the same stamp is
  refused before it reads a thing — then read the manifest, refuse if a target file
  exists, take `COMPLETE` down, copy each staged file in as `<name>.skill` with
  `SNAPSHOT_MODE`, rewrite `snapshot.json`, re-write `COMPLETE`, and release the lock last
  and on every way out — the same order as `file_archive`, for the same reason. It never
  touches `export.zip`, `parts` or `export_fingerprint`. On a stamp that does not exist it
  creates the directory — its own atomic lock — and writes a manifest whose `archive` is
  empty, so `Store.rows()` reads it as a complete snapshot rather than an unreadable one.
  Not `unlink` as the lock: measured on macOS, two unlinks of one file both succeed
  (ADR 0011).
- **Filenames**: `<name>.skill`, where `name` is the listing's, which the vendor already
  constrains to lowercase letters, numbers and hyphens. Anything outside that set is slugged;
  a collision takes `-1`, `-2`, `-3` in listing order. `allowAndName` means the vendor's
  suggested filename never reaches a path (§66), which is why the name comes from the
  listing.
- **The manifest.** `Snapshot` gains `skills: list[SkillFile]`, and `Counts` gains
  `skills: int`. `SkillFile` holds `name`, `filename`, `bytes`, `sha256`, `enabled` and
  `plugin: bool` — a label and numbers (§38). Not the display name and not the description:
  both are inside the vendor's file, which is the copy that matters.
- **`SnapshotRow` and the listing** learn `skills`, so `dataporter snapshots` reports a
  skills-only snapshot as something other than `0 conversations`.
- **Gaps** (§93): a listed skill whose fetch does not land is a `Gap` of kind
  `store.SKILL_GAP` (`skill_not_downloaded`), with a count and the reason an operator reads
  — `1 skill could not be downloaded`. The stop reason `download.fetch` gave — refused,
  stalled, cancelled — goes to the run log and not into the manifest, which §38 keeps to
  labels and numbers. The run still exits `0`. An append **replaces** a prior run's skill
  gaps rather than stacking them, so a second run that lands the skill clears the gap
  (§93's "a second run fixes"); an archive's `bytes_not_in_export` gap is another kind and
  is kept. Failing `org_js` or `list_js` is a `BrowserError`, nothing is
  filed, and the exit code is the one that read failed with.
- **The blocks** (§94), golden:

  ```text
  Claude skills — work

  Downloaded 2 skills in 4s.
  2 skills.

  Snapshot: ~/.dataporter/store/claude/work/2026-09-18T09-14-02Z/skills
  ```

  and, for an account that wrote none:

  ```text
  Claude skills — work

  No skills of your own to extract.
  ```

  New constants beside `extract`'s: `SKILLS_HEADER`, `SKILLS_DOWNLOADED`, `SKILLS_COUNT`,
  `NO_SKILLS`. `GAP_LINE` and `SNAPSHOT_LINE` are `extract`'s, unchanged. `1 skill.` is
  singular, as `GAPS_ONE` already is.
- **Unattended** (§89): `--non-interactive` is allowed, and a read that fails headless
  carries `extract.PANEL_MISSING_HEADLESS` itself — the ask's own hint, cited rather than
  re-typed, because the reads are made on the page the ask stands on. That page is the app
  shell, which `docs/LIMITATIONS.md` records as never resolving past the vendor's
  attestation.
- **The glossary.** `CONTEXT.md` gains **Skill**, widens **Extraction** and extends
  **Surface**. **Export page** is left alone: this command clicks nothing, so "the one place
  the tool clicks anything in a source account" stays true of it.
- **Paperwork**: `01`'s command surface and `23`'s operations table amended in place with an
  *Amended by [`66`]* note; the README's command table; `specs/README.md`'s index, sequence
  and status table; [ADR 0011](../../docs/adr/0011-snapshots-grow-but-never-change.md);
  and [`LIMITATIONS.md`](../../docs/LIMITATIONS.md)'s headless entry, which says *the
  ask* today and is true of this command for the same reason.

## Out of scope

- The mock's skills pages, the UI-map rows turning *observed*, and the rehearsal — [`67`](67-the-mock-grows-skills.md).
- Putting a skill back into an account (§95). The site takes a `.skill` file by hand.
- Any other vendor's skills. ChatGPT and Gemini have no equivalent (§95).
- A structural bot-check probe. Still `62`'s, still undone.

## Design notes

**Why the API and not the page.** The spike of 2026-09-18 found the download is a real
address — the menu item fetches it and only *presents* the bytes as a blob — and that
authorship is a field, `creator_type`, whose values are `anthropic` and `user`. Reading the
list instead of the page therefore costs nothing and buys three things: no language
surface at all (the alternative was matching a menu item by its icon's path, because
"Download" is a word), no dependency on a React render that `62` measured at 2.9 s, and the
skill `id` that the download address needs, which the DOM only yields by opening each
detail page. The testids exist and are recorded in the UI map as the structural equivalent;
no selector ships.

**Why the reads happen on the export page and the skills page is never opened.** The
watch sketches every navigation (`watch.py`), and a sketch keeps the accessible *name* of
every `button` (`sketch.LABELLED_ROLES`). On `/customize/skills/mine` those names are
*View <name>*, *More actions for <name>* and *Turn off <name>* — so one navigation there
would put every skill's name into the trace, which §46 forbids and no guard would catch,
because a control's label is exactly what a sketch is allowed to keep. The two reads are
same-origin `fetch`es and work from any page on the origin, and the export page is the one
already inside the wall, already sketched by every ask, and labelled with nothing of the
account's. So the tab stands there, and the wall gains one door rather than two.

**Why an in-page `fetch` does not reopen ADR 0008.** That ADR withdrew a design in which
the tool held the vendor's credential and made authenticated requests itself. Here the
browser makes the requests, on the page, on the vendor's origin; the tool constructs no
`Authorization` header, reads no cookie, and could not perform either read outside Chrome.
What the ADR protects — the cookie never leaves the browser — is exactly what this keeps.
§46 is untouched: the expressions return counts and identifiers, the trace records that a
read happened and how many came back, and no response value is written.

**Why append-only rather than a sidecar.** A `skills/skills.json` of its own would have left
`snapshot.json` untouched and kept §33 literally true. It was rejected because `snapshots`
would then be blind to skills unless taught to read two manifests, and a snapshot whose
manifest does not name a file in its own directory is the thing §32 exists to prevent. What
is given up is narrow and is [ADR 0011](../../docs/adr/0011-snapshots-grow-but-never-change.md):
the manifest may be written more than once. No skill file is ever rewritten, nothing is
renamed, and the marker still lands last.

**Why an unknown `creator_type` is not ours.** The spike saw two values. A third — for a
skill shared into the account, or authored by an organisation — would be somebody else's,
and the failure modes are not symmetrical: filing a skill that is not ours puts another
party's work in this account's snapshot, while missing one of ours is a gap a person
notices and a second run fixes.

**Why no empty snapshot** (§94). An `extract` with nothing to file is impossible — an
archive either arrived or the run failed — so the store has never had to say what an empty
snapshot means. Rather than answer that now, an account with no skills of its own files
nothing and says so.

## Acceptance criteria

1. `dataporter extract-skills --help` lists `--source`, `--account` and `--stamp`, and
   `dataporter --help` lists `extract-skills`. `tests/test_cli.py`'s `COMMANDS` holds it.
2. The command body in `cli.py` contains no `if`, `for`, `while`, `try` or `with` —
   `test_every_command_is_an_interface` passes unchanged.
3. `--stamp yesterday`, `--stamp ../../x` and `--stamp 2026-09-18T09:14:02Z` each exit `2`
   with a `UsageError`, and no browser is launched.
4. Against a fake page answering `LIST_TAG` with three skills, two `user` and one
   `anthropic`, exactly two `download.fetch` calls are made, and the `anthropic` one is not
   among them.
5. A listing entry whose `creator_type` is `"acme"` is not fetched.
6. The two blocks in **In scope** are produced byte for byte, stdout compared with `==`,
   including the singular `1 skill.` and the omission of `Gaps:` when there are none.
7. Run twice into the same `--stamp`: the second run refuses the files it already filed and
   exits non-zero, having rewritten nothing. `export.zip` and `export_fingerprint` are
   byte-identical before and after both runs.
8. `--stamp` naming a directory that does not exist creates it, and `dataporter snapshots`
   then lists that snapshot as complete rather than unreadable.
9. A skill whose fetch stalls produces one `Gap` of kind `skills.NOT_DOWNLOADED`, the run
   exits `0`, and the block carries the `Gaps:` line.
10. An account whose listing holds no `user` skill prints `No skills of your own to
    extract.`, exits `0`, and creates no directory under the store.
11. `tests/test_operations.py` runs the operation through the library and through the CLI
    and compares stdout, stderr and exit code byte for byte.
12. `tests/test_sources.py` pins the widened extraction pattern; `/customize/skills/mine`,
    `/customize/skills/discover` and the list address are all refused by it, and the
    download address is refused by the sign-in's wall.
13. The same run against the mock files the same skills the mock's ledger says it served —
    met by [`docs/rehearsal-04.md`](../../docs/rehearsal-04.md) on 2026-09-18.
14. *unverified* — a real account: the block matches, and `snapshots` reports the count.

## Risks

- **The addresses are the vendor's private API and may change without notice.** This is the
  real cost of the choice, and it is not hypothetical: `list-skills` and
  `download-dot-skill-file` are what claude.ai's own page calls, and nothing promises them.
  What surfaces it is a failing read rather than a silent wrong answer — both are one
  request with a status — and the fallback is written down in the UI map's `skill menu` row
  rather than lost.
- **Two tabs on the surface is a refusal**, as it is for every helper: the reads need the
  one tab, and `chosen_tab` says `ambiguous_tab` rather than guessing.
- **A third `creator_type`** would silently exclude skills that are the account's. Criterion
  5 pins the behaviour; only a person looking at an account that has one will notice the
  policy is wrong.
- **The rows this is built on are `*unknown*`.** They were read on a personal account and
  nothing could be committed under `spike/` (the throwaway-account rule), exactly as `51`'s
  rows were. The code is therefore built on a reading, not on evidence, and [`67`] plus a
  throwaway-account run are what close that.
- **`display_name` is not kept in the manifest.** A restore that wanted it reads the
  `.skill` file. If it turns out the vendor's file does not carry it, this is wrong and
  `SkillFile` grows a field.
- **One browser at a time** still holds: a running Chrome for the destination makes this
  `PortInUseError`, exit `2`.
