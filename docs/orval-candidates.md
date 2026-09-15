# orval and dataporter

[orval](https://github.com/lukin0110/orval/) has been a declared dependency since
`266ef93` and was imported nowhere. This file records what it now replaces, what it
must never replace, and what dataporter has written that belongs upstream in it.

Everything below was checked against **orval 0.0.13** by reading its source and
running the functions in question. A claim that a swap is byte-identical means it
was executed, not inferred.

**0.0.12 is the first bump this file has driven.** It ships four things this
document asked for — `strip_control` (C1), `to_utc` (C2), a `truncate` that
respects its limit (D1) and `coalesce` overloads that narrow (D2) — so the
sections below are the second pass, not the first. What the previous pass
deferred and 0.0.12 did not answer is still deferred, with the same reasons.

**The third pass is brief `06`'s** (`47`), made while the ChatGPT half was
written: one adoption in new code, one deliberate non-swap verified by running
both spellings, one candidate that gained the real caller it was waiting for,
and two that gained none. Nothing below is filed upstream from here; this file
is the record, and filing is a separate decision.

**The fourth pass bumps to 0.0.13**, which ships three of this file's own
candidates — `unique` (C5), `fence` (C7) and `has_control` (C8) — plus `squish`,
`truncate_bytes`, `to_tz`, and a `hashify` that hashes `bytes` directly instead
of pickling them. Eight call sites move to library code this pass: one each
for `unique`, `fence`, `has_control` and the fixed `hashify`, three for
`squish`, and one more, `store.stamp_of`, that turns out to be a *third*
hand-rolled naive-to-UTC normaliser carrying the same latent hole
`export.model._utc` and `state._to_utc` already closed — found by re-reading
every `astimezone` in the tree while checking `to_tz`'s candidacy, not by
anything 0.0.13 changed. `unique` also settles a question the third pass left
open: run against `plan._distinct`, it reproduces the dedup exactly, and is
rejected anyway — see B.

## A. Adopted

| Site | Was | Now | Since |
| --- | --- | --- | --- |
| `log.strict_by_default` | `os.environ.get(...) not in ("", "0")` | `to_bool(..., default=False)` | 0.0.11 |
| `seed.sha256_of` | `hashlib.sha256(text.encode("utf-8")).hexdigest()` | `hashify(text)` | 0.0.11 |
| `log.run_log_path` | `datetime.now(UTC)` | `utcnow()` | 0.0.11 |
| `log.safe_token` | `CONTROL_CHARACTERS.sub("?", value)` | `strip_control(value, "?")` | 0.0.12 |
| `hermes.prompt._one_line` | `log.CONTROL_CHARACTERS.sub("?", value)` | `strip_control(value, "?")` | 0.0.12 |
| `plan.safe_component` | `log.CONTROL_CHARACTERS.search(value)` → `strip_control(value) != value` | `has_control(value)` | 0.0.13 |
| `export.model._utc` | two-branch naive/aware normalise | `to_utc(value)` | 0.0.12 |
| `state._to_utc` | two-branch naive/aware normalise | `to_utc(value)` | 0.0.12 |
| `store.stamp_of` | `tzinfo is None` check, then `.astimezone(UTC)` | `to_utc(instant)` | 0.0.13 |
| `config.bootstrap_workspace` | three early returns | `coalesce_lazy(...)` | 0.0.12 |
| `cdp.Page.set_file_input_files` | `root.get("root", {}).get("nodeId")` | `deep_get(root, "root.nodeId")` | 0.0.11 |
| `probe.pending_dialogs` | `.get("params", {}).get("type", "dialog")` | `deep_get(item, "params.type", "dialog")` | 0.0.11 |
| `export.chatgpt._attachment_ids` | — (new in `43`) | `deep_get(node, "message.metadata.attachments")` | 0.0.12 |
| `export.chatgpt.read`'s `_unique` | hand-rolled seen-set loop | `unique(referenced)` | 0.0.13 |
| `render._fence_for` | hand-rolled longest-run scan | `fence(content)` | 0.0.13 |
| `export.source.read_export`'s fingerprint | `hashlib.sha256(raw).hexdigest()` | `hashify(raw)` | 0.0.13 |
| `progress.detail_of`, `report.ErrorRecord.describe`, `probe.normalise_title` | `" ".join(v.split())` | `squish(v)` | 0.0.13 |

**`to_bool` was a behaviour change, and remains the only user-visible one here.**
Under the old expression `DATAPORTER_LOG_STRICT=false` turned the content guard's
strict mode *on*, as did `no`, `off` and every typo — anything non-empty that was
not the single character `0`. It now reads the spellings `to_bool` recognises
(`1`, `true`, `yes`, `y`, `t`, `on`, case-insensitively) and treats everything
else, unrecognised values included, as off. Nothing contradicted this:
`specs/impl/01-foundation.md` does not pin the variable and no test touched it.
`tests/test_log.py` now does.

**`hashify` of a `str` is sha256 over `str.encode()`, which is UTF-8** — the same
digest `sha256_of` always returned, confirmed by running both. The golden files
under `tests/fixtures/seeds/` did not move. The wrapper function stays, because
`08`'s paste helper and the tests name it, and
`test_sha256_of_is_sha256_over_utf8_bytes` pins the digest to its definition rather
than to orval's continued agreement: this value is compared against what a browser
composer holds, and a change upstream would fail every paste for a reason nobody
could see from the failure.

**`strip_control` retires `log.CONTROL_CHARACTERS` entirely.** The constant was
`re.compile(r"[\x00-\x1f\x7f]")` — the same set, the same reason — and it was
public only so `plan.py` could read it rather than compile a second copy. orval
now owns the rule, so the constant is gone and `log.py` no longer imports `re`.
All three call sites were checked over 20,000 random strings drawn from an
alphabet of C0 controls, DEL, ASCII, accented and CJK characters, zero-width
space, and the regex-replacement metacharacters `\` and `$`: `sub("?")`,
`sub("")` and `bool(search(...)) == (strip_control(v) != v)` each matched on
every case. The metacharacters matter — orval substitutes through a callable
precisely so a `\1` in the replacement is not expanded as a template — but
dataporter passes `"?"` and `""`, so no call site depended on it either way.

The predicate at `plan.safe_component` read as a comparison rather than a test
because orval had no `has_control` — that was candidate C8, and it now reads
as `has_control(value)`; see below.

**`to_utc` replaces two hand-rolled normalisers, and `export.model._utc` keeps
its warning.** orval has no hook for one, so the naive branch survives to log
`export naive timestamp` and then defers to `to_utc`. The swap is exactly
equivalent on every datetime an export can produce, confirmed against naive, UTC,
`+02:00` and `-07:00` values. It is *not* equivalent on one input dataporter
cannot receive: a `tzinfo` whose `utcoffset()` returns `None` is naive by the
standard library's own definition, which `tzinfo is None` misses and orval's test
catches. The old code sent such a value to `astimezone`, which reads it as
**system-local** time — verified as a four-hour error under `TZ=America/New_York`
and invisible under `TZ=UTC`. Pydantic never builds such a `tzinfo` from JSON, so
this closes a hole rather than fixing a bug; it is written down because "we tested
it on a UTC machine" is how that class of bug survives.

`state._to_utc` keeps its `.replace(microsecond=0)` — whole seconds are §7's
format, not orval's business.

**`coalesce_lazy` was blocked by D2 until 0.0.12 and is adopted now that it is
not.** The chain is the one the docstrings advertise, and the `ty` result is the
whole point: the same three-callable file is rejected under 0.0.11
(`invalid-return-type: expected Path, found Path | None`) and passes under 0.0.12,
both run under `--error-on-warning`. It needed one new named function,
`_workspace_from_env`, because a `coalesce_lazy` argument must be a callable
returning `Path | None`; that is a wash on line count and a small gain in naming —
the blank-string-is-not-`Path(".")` rule now has a docstring of its own instead of
living inside an `if`.

**`deep_get` is not new in 0.0.12 and was simply missed the first time.** Both
sites read untrusted JSON — a CDP reply and a `Page.javascriptDialogOpening`
event — where the `{}` in `.get("root", {})` exists only to keep a second `.get`
from raising. `deep_get(root, "root.nodeId")` says the same thing without the
sentinel, and `deep_get(item, "params.type", "dialog")` puts the real default
where a reader looks for it.

**This one is not byte-identical, and the difference is the reason to make it.**
Run against present, absent, null, wrongly-typed and present-but-null payloads,
the two agree everywhere except on a wrongly-typed *intermediate* — `{"root":
null}`, `{"params": [1]}` — where the old chain raises `AttributeError` (`None`
has no `.get`) and `deep_get` returns the default. The sentinel `{}` only ever
guarded a *missing* key; a key present with the wrong type walked straight past
it. So the old spelling crashed on exactly the malformed payload it looked like
it was defending against.

Neither case is reachable from a real browser — Chrome does not answer
`DOM.getDocument` with `{"root": null}` — so this is a defensive path either
way. `pending_dialogs` degrades better for it: it still reports that a dialog is
open, under the generic label its default already exists to supply, rather than
failing the enumeration, and a safety listing that raises is worse than one that
says `javascript:dialog`.

`set_file_input_files` needed a guard to be an improvement, which Copilot caught
on the pull request and this file had wrong in its first draft. `deep_get`
turning a malformed reply into `None` does *not* reach the nearby
`no element matches {selector}`: `None` goes on to `DOM.querySelector`, which a
real Chrome refuses and `send` reports as `DOM.querySelector failed: …` — naming
a call that never could have worked instead of the document that was never read.
Against a fake that ignores the `nodeId` it is worse still, and does not fail at
all. So `root_id is None` is now checked where it is read, and
`test_set_file_input_files_without_a_document_node` pins the message. The lesson
generalises past this call site: `deep_get` replaces a raise with a default, so
every site that swaps to it has to answer what the default then *does*.

**`has_control` retires `plan.safe_component`'s comparison spelling.** C8 asked
for exactly this the pass it was written, and 0.0.13 ships it unchanged:
`bool(_CONTROL_RE.search(string))`, the same pattern `strip_control` already
compiled. `strip_control(value) != value` and `has_control(value)` agree on
every input by construction — one runs the search the other builds a
throwaway string to compare — so this is a rename, not a behaviour check.

**`store.stamp_of` was a third hand-rolled naive-to-UTC normaliser, not caught
by the passes that fixed the first two.** It predates neither: `export.model._utc`
and `state._to_utc` were rewritten under 0.0.12, and this one was found this
pass by grepping every `astimezone` in the tree while scoping `to_tz`'s
candidacy (C-worthy or not — see C3's neighbourhood). Its bug is the identical
one `export.model._utc`'s entry above already describes: `if instant.tzinfo is
None` misses a `tzinfo` that is present but whose `utcoffset()` returns `None`,
and the old code sent such a value straight to `.astimezone(UTC)`, which reads
a naive datetime as *system-local* time rather than raising or refusing it.
`to_utc(instant)` closes the same hole here it closed twice already, confirmed
against naive, UTC and `+02:00` values — the three `tests/test_store.py`
already exercises — with no change to `STAMP_FORMAT` or `parse_stamp`'s
inverse. Nothing in `store.py` can construct the degenerate `tzinfo` today, so
as with the other two this is a hole narrowed rather than a live bug fixed.

**`unique` retires the fourth hand-rolled variant, `export.chatgpt._unique`,
the one C5 was written against.** `values: Iterable[str]` with no `key`
argument is exactly `unique`'s default case — identity, hashable — confirmed
over 20,000 random string sequences. The two remaining calls at that site
(`missing` and the `"referenced"` count) now share one `unique(referenced)`
list instead of computing it twice, which the old two separate `_unique(...)`
calls did not.

**`fence` retires `render._fence_for` outright.** Same algorithm — longest run
of the fence character plus one, floored at a minimum — confirmed byte-
identical over 20,000 random strings mixing backticks, letters and whitespace.
The local variable at the call site is renamed from `fence` to `marker`
because the import now owns that name.

**`hashify`'s fingerprint non-swap is retracted: 0.0.13 fixed the reason for
it.** The `export.source.read_export` comment explained, correctly for 0.0.11
and 0.0.12, that `hashify` pickled anything that was not a `str`, so calling it
on the conversations file's raw bytes would hash a pickle rather than the
bytes. 0.0.13 adds a `bytes | bytearray | memoryview` branch that hashes the
raw content directly — confirmed against `hashlib.sha256(...).hexdigest()`
over twenty random byte strings, the empty string, a `bytearray` and a
`memoryview`, all exact matches. `hashify(raw)` is now the plain sha256 the
site always wanted, and the `import hashlib` this was the last user of is
gone.

**`squish` retires three copies of `" ".join(v.split())`**: `progress.detail_of`,
`report.ErrorRecord.describe` and `probe.normalise_title`. All three are that
exact expression, character for character, so `squish` is byte-identical by
inspection; a 20,000-string fuzz run over an alphabet including a non-breaking
space and an em space (`squish` collapses Unicode whitespace, same as
`str.split()` with no argument) found no disagreement either. None of the
three had a comment explaining the expression — collapsing whitespace to
compare or store a value is not a subtle operation — so the swap is pure
deduplication, three call sites down to one import.

## B. Deliberate non-swaps

Each of these looks like an orval call and is not. They are written down so the
analysis is not repeated, and so that "adopt more orval" never becomes a reason to
break one of them.

| Tempting | Why not |
| --- | --- |
| `summary._number` → `pretty_number` | §9 is a golden block compared byte for byte in `tests/test_summary.py`. It reads `4,821`, not `4.8K` |
| `render._render_attachment`'s `{n} bytes` → `pretty_bytes` | The seed format is pinned by `tests/fixtures/seeds/`. `04` writes `{file_size} bytes` and a chat receives exactly that |
| `render._split_paragraphs` / `_pack` → `chunkify` | `chunkify` cuts a sequence into fixed-size lists. These pack strings against a character budget that itself changes with the envelope, and must never split a fragment |
| `seed.max_chars` → `estimate_tokens` | The constraint is the composer's character limit, not a context window. `10` measures the real number against the real UI |
| `plan._distinct` → `unique(entries, key=[...])` | Run against `unique` with a two-callable `key` (filename, then uuid-or-`id(entry)` for an entry with none) over 20,000 random attachment lists, the two never disagreed. Rejected anyway: the second key function needs `id(entry)` as a per-item "never collides" placeholder, because a single shared sentinel would make every entry *without* a uuid collide with every other one. That is a correctness dependency on object identity a reader has to independently verify, for a saving of two lines over the current set-of-keys loop |
| `export.source._collect_duplicates` → `unique` | Not a dedup at all: it flags every *repeat* occurrence of a uuid as `duplicate_message_uuid`, it does not return the survivors. `unique` would have to be run and then diffed against the original list to recover a count, which is not shorter or clearer than the one loop already there |
| `export.model.Conversation._split`'s `by_uuid.setdefault` / `positions.setdefault` | Builds two dicts (uuid → first message, uuid → first position) for O(1) lookup during the parent-chain walk two lines below; `unique` returns a list, not the two indexes this code reads from for the rest of the function |
| `log.safe_token`'s bounded cut → `truncate` | D1 is fixed, so `truncate(v, limit, suffix="")` is now exactly `v[:limit]` — verified over every combination of four strings and five limits. The slice stays anyway: it needs no import to read, and `truncate` raises on `limit <= 0` where `safe_token(v, 0)` returns `(empty)`. A helper that turns a degenerate argument into an exception is not an improvement on a slice that cannot fail |
| `probe._expect_const`'s `[item for item in expect if item]` → `compact` | `compact(expect, none_only=False)` is equivalent for a `Sequence[str]`, but the comprehension carries a comment explaining *which* falsy value matters and why (`indexOf('')` is 0 on every string). `none_only=False` hides that behind a flag |
| Any `@timing` | It logs an f-string through `logging.getLogger("orval.utils")` — outside the `dataporter` logger, so past `ContentGuard`, and against this repo's rule that log messages are constants and variable data goes in `extra` |
| `runner`/`helpers` elapsed times → `pretty_duration` | `elapsed_s` and `elapsed_ms` are numeric fields in JSON-lines records, read by `19`'s parser and by `21`'s instruments, and stay numbers. The one duration a person reads — §31's `Downloaded … in 1m 6s.` (`60`) — is `pretty_duration` already |
| `config._describe` / `source._describe` / `export.chatgpt._envelope`'s inline copy | Genuinely duplicated — three times since `43` — but shaped by pydantic's `ValidationError`. orval has no dependencies and should keep none |
| `extract.DOWNLOADED`'s `{size / MEGABYTE:.1f}` → `pretty_bytes(size, "ds", precision=1)` | **Verified not byte-identical** by running both over the same sizes: `pretty_bytes` picks a unit — `999_999` renders `1000.0 KB`, `1_582` renders `1.6 KB`, `5_000_000_000` renders `5.0 GB` — and §31's line is always megabytes to one decimal, `Downloaded 0.0 MB.` for a small archive included, which is what `docs/rehearsal-03.md` prints twice. A golden string, and the unit is the brief's |

## C. Candidates for orval

Each entry names the source it generalises from, so the proposed function has a
real caller to be checked against. **C1 and C2 shipped in 0.0.12, and C5, C7 and
C8 shipped in 0.0.13**; all five are kept here, struck through, so the list
reads as a record rather than a wish.

### ~~C1 — `orval.strings.strip_control(string, replacement="")`~~ — shipped in 0.0.12

Landed as proposed, including the `replacement` parameter. The implementation
went further than the proposal in one way worth noting: it substitutes through a
callable so the replacement is used literally, which the obvious `re.sub(pattern,
replacement, string)` spelling gets wrong for any replacement containing a
backslash. See A for the three call sites it retired.

### ~~C2 — `orval.datetimes.to_utc(value, *, assume_utc=True)`~~ — shipped in 0.0.12

Landed as proposed, with `assume_utc=False` raising as suggested. Its naive test
is `tzinfo is None or tzinfo.utcoffset(value) is None`, which is stricter than
the version dataporter had written twice — see A.

### C3 — `orval.datetimes.iso_utc(value, timespec="milliseconds")`

*From `log.JsonlFormatter.format`, `state._format_instant`, `browser.helpers` and
`browser.launcher`.*

*Third pass:* no new site. The ChatGPT half writes every timestamp through
`trace.timestamp`, which is one of the four; the count stays four.

`value.isoformat(timespec=...).replace("+00:00", "Z")`. **This is now the
strongest candidate on the list: dataporter writes the line four times**, at two
different `timespec`s, up from one site when this file was first written. Every
JSON-lines logger writes it, and the `replace` is the part people forget, so the
field ends up in two spellings across one file. `launcher.py` carries a comment
saying the `Z` is hand-rolled because orval has no `iso_utc`; that comment is the
candidate.

### C4 — `orval.paths.is_safe_component(name)` and `is_within(root, candidate)`

*From `plan.safe_component` and `plan._within`.*

A new module. `is_safe_component` answers "is this one ordinary path component" —
non-empty, not `.` or `..`, no separator, no control character. `is_within` answers
"does this really sit under that root once symlinks resolve". Both guard the same
mistake: joining a name from an untrusted file to a path. Both are copy-pasted into
every project that reads someone else's archive, and both are easy to get subtly
wrong — `plan._locate` records the *resolved* path rather than the name that led to
it, precisely so a symlink cannot be swapped between the check and the read.

Now that `strip_control` exists, `is_safe_component` is three lines on top of it,
which makes the case for it stronger rather than weaker: the remaining two lines
are the ones people get wrong.

*Third pass:* no new caller, deliberately. `45`'s download is named by the
browser's own guid (`allowAndName`), so a name the vendor chose never reaches a
path; and `43` reads the archive's members from the stream, as `02` does, so a
member name is never joined to one either. The case for the helper stands on
`plan`'s two sites and is not strengthened here.

### ~~C5 — `orval.containers.unique(seq, key=None)`~~ — shipped in 0.0.13

*Originally from `plan._distinct`, `source._collect_duplicates`,
`model.Conversation._split` and, since `43`, `export.chatgpt._unique` — the
fourth hand-rolling of order-preserving deduplication, and the one this entry
was written against.*

Landed as proposed for the plain case, and the `key` design went further than
the proposal asked: an iterable of callables deduplicates on *any* of them,
each with its own memory, which is exactly "a callable per element or a key
returning a tuple" as originally imagined. `export.chatgpt._unique` is
retired by it; see A.

The other three original callers turned out not to be swaps once `unique`
actually existed to check them against, which the wish could not surface:
`plan._distinct` reproduces exactly under a two-callable `key` but is kept for
the sentinel it would need (see B), `source._collect_duplicates` flags
duplicates rather than filtering them, and `export.model.Conversation._split`
needs the two dicts its `setdefault` calls build, not the list `unique`
returns. Three non-swaps out of the three original callers is not a reason to
have skipped proposing the function — the fourth caller was real and is
retired — but it does mean the general `key` design reached fewer of this
file's own sites than hoped.

### C6 — `orval.token_utils.chunk_text(text, budget, separator="\n\n")`

*From `render._split_paragraphs`.*

Split a string into pieces no longer than `budget`, preferring `separator`
boundaries and hard-cutting only a piece that is indivisible on its own. This is the
sibling `truncate_tokens` is missing: `truncate_tokens` throws the tail away, and
what anyone feeding long text to an LLM actually needs is every piece, in order. A
`chunk_tokens(text, budget)` measured with `estimate_tokens` follows from the same
implementation.

### ~~C7 — `orval.strings.fence(content, char="\`", minimum=3)`~~ — shipped in 0.0.13

*Originally from `render._fence_for`: the shortest fence — `max(minimum,
longest run of char in content + 1)` — that untrusted content placed inside it
cannot close early.*

Landed as proposed, `char` and `minimum` parameters included; `render._fence_for`
only ever needed the defaults. See A for the swap and the fuzz run that checked it.

### ~~C8 — `orval.strings.has_control(string)`~~ — shipped in 0.0.13

*Originally from `plan.safe_component`, a direct consequence of C1 shipping:
`strip_control` answers "give me this without control characters", and
`safe_component` wants "does this contain one" — a rejection, not a repair —
so it asked `strip_control(v) != v`, building a string it threw away in order
to compare it.*

Landed as proposed: one line, `bool(_CONTROL_RE.search(string))`, reusing the
pattern `strip_control` already compiles. See A for the swap. `strip_styling`
still has no `has_styling` predicate to match it, so that half of the original
pairing is unaddressed.

**0.0.13 also ships `squish`, `truncate_bytes` and `to_tz`, none proposed here.**
`squish` had three real callers waiting for it — see A — found by grepping for
its own implementation, `" ".join(s.split())`, once the function existed to
grep for. `truncate_bytes` has no site: nothing in dataporter truncates
against a byte budget, only `log.safe_token`'s character count (see B) and
`seed.max_chars`'s composer limit (see B) — both explicitly not bytes. `to_tz`
has no site either, and is unlikely to: everything dataporter stamps, logs or
compares is UTC by §33 and `docs/export-format.md`, and `to_utc` — now written
in terms of `to_tz(value, UTC)` — is the whole of what this tool ever converts
to. Worth re-checking `truncate_bytes` if a future protocol boundary (a
header, a column, a wire format) imposes a byte budget.

### Considered and rejected as too specific to this project

`summary.totals_lines` and `_breakdown_lines` (the width rule is the brief's §9, not
a general one), `source._token`, `render.format_timestamp`, `seed.part_filename`,
and `render.normalise` — one stdlib call, and `strip_accents` already normalises
internally.

## D. Defects

### ~~D1 — `truncate` returns strings longer than the limit it was given~~ — fixed in 0.0.12

`20d0fa3` changed the slice to `string[: number - len(suffix)]` and added a
`ValueError` when the suffix is not shorter than the limit. Confirmed by running
the two cases this file reported:

```python
truncate("hello world", 8)   # 'hello...' — was 'hello w...', ten characters
truncate("abcdef", 3, "")    # 'abc'      — was 'ab'
```

The limit is now an actual bound and an empty suffix is a plain cut, both as
proposed. `log.safe_token` keeps its slice anyway; see B for why.

### ~~D2 — `coalesce` / `coalesce_lazy` are unusable under a strict type checker~~ — fixed in 0.0.12

`f49c9b5` added the `@overload` chain this file proposed, enumerating arities up
to five so that a chain whose last value cannot be `None` returns `T`. Confirmed
by type-checking one file against both versions under
`ty check --error-on-warning`:

```
orval 0.0.11:  error[invalid-return-type]: expected `Path`, found `Path | None`
orval 0.0.12:  All checks passed!
```

`config.bootstrap_workspace` is the call site and is now written as the chain.
The five-argument ceiling is not a limitation anything here approaches.

### ~~D3 — the `v0.0.12` tag points one commit before the version it names~~ — fixed

`v0.0.12` now points at `af19f8f`, whose `pyproject.toml` reads
`version = "0.0.12"` — the commit this entry asked for, not `6e686f0`. `v0.0.13`
was never wrong: it points at `56f1987` ("Bump version from 0.0.12 to 0.0.13"),
whose `pyproject.toml` reads `version = "0.0.13"`, tagged correctly the first
time. Both confirmed by cloning `lukin0110/orval` and reading `pyproject.toml`
at each tag directly, not inferred from release notes.

The published artefact was always fine: the three modules in the 0.0.12 wheel
were byte-identical to `origin/main` (sha256 over `strings.py`, `datetimes.py`
and `utils.py` matched), so everything the second pass reviewed against 0.0.12
is what shipped. Only the tag was misplaced, and it no longer is.
