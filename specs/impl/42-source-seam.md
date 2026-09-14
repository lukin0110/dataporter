# 42 — The source seam

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief 06](../06-chatgpt-extraction.md) §60; brief 03 §34, made concrete;
brief 04 §50, kept
**Depends on:** [30](30-store-and-snapshot.md), [31](31-source-session-and-ask.md),
[33](33-trace-and-move.md)–[35](35-watch.md)
**Enables:** [43](43-chatgpt-archive.md), [44](44-chatgpt-session-and-ask.md),
[45](45-fetch-through-the-session.md)
**Status:** Done

## Goal

One object per vendor that gathers what §34 says a source knows, with Claude moved onto it
and every byte it prints unchanged. Nothing ChatGPT lands here: the seam is the slice, and
the golden tests are the proof that nothing moved but the code. Beside it, one rename:
`ExportSource` becomes `ExportView`, because the glossary's **Source** is the vendor and a
read-only view of an archive is not one.

## In scope

- **`dataporter.sources`** (new package): `base.Source`, a frozen dataclass compared by
  identity — `name`, `display_name`, `host`, `auth_hosts`, `login_url`, `sign_in_paths`,
  `app_paths`, `export_page_path`, `selectors`, `fetch_needs_session`,
  `signed_out_at_root`, `unattended_signin` (`agent` | `walk`), `ask_lines`, `counts_line`,
  `login_prompt`, and two hooks, `recognise(names)` and `read(view) -> Reading`; and
  `base.Reading` — `conversations`, `fingerprint`, `projects`, `memories`, `files`
  (`None` for a source that does not count them), `missing_files`. `claude.CLAUDE` carries
  every string `31` spelled: the host, the placeholder path, the three selectors, the two
  sentences of the ask block, the count line, the `login` prompt. `__init__.REGISTRY` maps
  name to source, `of(settings)` looks the invocation's up, `recognised(names)` says whose
  archive a set of members looks like. The package imports nothing of the browser and
  nothing of the store; `claude.read` imports the export reader inside the function.
- **The registries derived** (`store.py`): `SOURCES` is the registry's keys and
  `SOURCE_NAMES` its display names; `config.with_account` is untouched.
- **A site with several hosts** (`browser/site.py`, `browser/helpers.py`): `Site` and
  `Surface` gain `hosts: tuple[str, ...]`, empty meaning the one host, so every existing
  construction reads as it did. `helpers.surface_tabs`, `session.tabs_on` (new;
  `claude_tabs` is the one-host spelling of it), `watch._attach` and `watch._request` look
  on every host; the watch records a certificate once **per host** and names the host on a
  navigation, a URL change or a request that is not on the site's own — so a one-host run
  writes every line `35` wrote and no other.
- **The derivation** (`browser/sites.py`, new): `extraction_site(source)`,
  `extraction_surface(source)`, `login_surface(source)`, `export_page_url(source)`,
  `not_the_export_page(source)`, and the two patterns, `extraction_pattern` and
  `login_pattern`, built as `24` and `31` built Claude's by hand: the site's host with the
  paths, then every auth host whole. Cached per source, so `session.site_of` and
  `export_page.EXTRACTION_SITE` are one object.
- **The Claude modules read the source**: `export_page` takes a `source` on every
  function, defaulting to `CLAUDE`, and keeps `31`'s names as aliases —
  `EXPORT_PAGE_PATH`, `EXPORT_PAGE_URL`, the three selectors, `EXTRACTION_SITE`,
  `EXTRACTION_SURFACE`, `EXPORT_PAGE_JS`, `NOT_THE_EXPORT_PAGE`; `signed_out` reads
  `signed_out_at_root` beside the `/login` redirect. `session.whose(settings)` answers
  where `login` opens, what it says and on which hosts it looks — `/new`, the prompt and
  `claude.ai` without an account, the source's with one — and `login`, `status`,
  `signed_in`, `current_state`, `wait_for_login` and `open_claude_tab` take the hosts.
  `signin` probes through `whose`. `extract.ask` launches on `sites.export_page_url`,
  watches `sites.extraction_site`, prints `source.ask_lines` and `source.counts_line`, and
  reads the archive through `source.read`. `login_form.LOGIN_SURFACE` is
  `sites.login_surface(CLAUDE)`. `probe.CLAUDE_HOST` is the source's `HOST`, spelled once.
- **The rename**: `export.ExportView`, in `export/source.py`, `export/__init__.py`,
  `extract.py`, `plan.py`'s docstring, `tests/test_export_source.py`, `spikes/sign_off.py`
  and the living specs that named it (`02`, `03`, `30`). No alias.
- **Tests** (`tests/test_sources.py`, plus one each in `tests/test_watch.py` and
  `tests/test_browser_helpers.py`): the registry holds Claude alone; the extraction site's
  selector table and the two walls' patterns are spelled out and compared byte for byte
  with what `31` and `24` wrote; a one-host site's `hosts` is its host; `surface_tabs`
  finds a tab on a second host; the watch names a second host and records its certificate
  too; importing `dataporter.sources` imports nothing of the browser, checked in a
  subprocess.

## Out of scope

- ChatGPT itself — the archive, the session, the ask, the fetch: `43`–`45`. Until `43`
  registers it, `--source chatgpt` exits `2` with `no such source: chatgpt`, as before.
- `Counts.files` in the manifest: `43`, where the first source that counts files lands.

## Design notes

- **Data and one hook, not a class per vendor.** Two vendors, both plain data; a
  `Protocol` with methods would invite each source to reach into the browser, and the
  browser is exactly what the store must not import to list two names. The site and the
  walls are derived on the browser's side, in `sites.py`, from the source's strings.
- **Compared by identity.** `eq=False`: there is one object per vendor, `sites` caches
  what it derives from each, and a mapping of selectors is not hashable anyway. Identity is
  also what `tests/test_browser_session.py` asks of `site_of` with `is`, and it holds.
- **`hosts` with an empty default rather than a second class.** Every Claude call site
  stays as written; the only observable widening — a certificate per host — is invisible
  for one host, and `test_watch.py`'s golden lines say so.
- **The patterns are built, not moved.** Building them from `sign_in_paths`, `app_paths`,
  the export page path and `auth_hosts` is what lets `44` write ChatGPT's two-host wall as
  data; the cost is that Claude's had to come out byte-identical, which two tests hold.
- **`ExportView`, no alias.** The clash is with a glossary term at the moment the term is
  being claimed in code; an alias would keep the clashing name on the typed-library
  surface (`25`), and there is no PyPI consumer to protect.
- **`login_form` and `sites` read each other once.** `sites.extraction_site` needs the
  credential selectors, which are spelled inside the credential seam and nowhere else;
  `login_form.LOGIN_SURFACE` needs `sites`. The import in `sites` is inside the function,
  taken when a site is first asked for, by which time `login_form`'s table exists.

## Acceptance criteria

- `make check` is green, and every golden test in `test_ask.py`, `test_extract.py`,
  `test_store.py`, `test_source_session.py`, `test_login_form.py`, `test_watch.py`,
  `test_trace.py` and `test_sketch.py` passes without an edit.
- `export_page.EXTRACTION_SITE.selectors` and `LOGIN_SURFACE.allowed.pattern` and
  `EXTRACTION_SURFACE.allowed.pattern` equal the values `31` and `24` spelled, pinned by
  tests that spell them again.
- `store.SOURCES == ("claude",)` and `extract --source chatgpt --account a` exits `2` with
  `no such source: chatgpt`.
- `grep -rn ExportSource src tests spikes` finds nothing.
- A subprocess that imports `dataporter.sources` has no `dataporter.browser.*` module
  loaded afterwards.
- *(Live, `46`'s.)* The extraction rehearsal against the mock claude.ai runs `login`, the
  ask and the fetch through the seam; that is what turns this slice `Done`.
  Met on 2026-09-14: the extraction rehearsal (`46`, [`docs/rehearsal-03.md`](../../docs/rehearsal-03.md)) ran `login`, the ask and the fetch through the seam against both mocks; `Done`.

## Risks

- **A `CLAUDE_HOST` consumer that filters tabs by `==` and was missed.** `verify.py`
  builds chat URLs and is the destination's; the tab-finding paths were all changed. A
  second host that a run never reaches is invisible until `44`'s tests reach one.
- **The lazy import between `login_form` and `sites`** works because `SELECTORS` is
  defined above `LOGIN_SURFACE`; moving the constant below it would fail at import, loudly.
