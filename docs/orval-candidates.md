# orval and dataporter

[orval](https://github.com/lukin0110/orval/) has been a declared dependency since
`266ef93` and was imported nowhere. This file records what it now replaces, what it
must never replace, and what dataporter has written that belongs upstream in it.

Everything below was checked against **orval 0.0.12** by reading its source and
running the functions in question. A claim that a swap is byte-identical means it
was executed, not inferred.

**0.0.12 is the first bump this file has driven.** It ships four things this
document asked for — `strip_control` (C1), `to_utc` (C2), a `truncate` that
respects its limit (D1) and `coalesce` overloads that narrow (D2) — so the
sections below are the second pass, not the first. What the previous pass
deferred and 0.0.12 did not answer is still deferred, with the same reasons.

## A. Adopted

| Site | Was | Now | Since |
| --- | --- | --- | --- |
| `log.strict_by_default` | `os.environ.get(...) not in ("", "0")` | `to_bool(..., default=False)` | 0.0.11 |
| `seed.sha256_of` | `hashlib.sha256(text.encode("utf-8")).hexdigest()` | `hashify(text)` | 0.0.11 |
| `log.run_log_path` | `datetime.now(UTC)` | `utcnow()` | 0.0.11 |
| `log.safe_token` | `CONTROL_CHARACTERS.sub("?", value)` | `strip_control(value, "?")` | 0.0.12 |
| `hermes.prompt._one_line` | `log.CONTROL_CHARACTERS.sub("?", value)` | `strip_control(value, "?")` | 0.0.12 |
| `plan.safe_component` | `log.CONTROL_CHARACTERS.search(value)` | `strip_control(value) != value` | 0.0.12 |
| `export.model._utc` | two-branch naive/aware normalise | `to_utc(value)` | 0.0.12 |
| `state._to_utc` | two-branch naive/aware normalise | `to_utc(value)` | 0.0.12 |
| `config.bootstrap_workspace` | three early returns | `coalesce_lazy(...)` | 0.0.12 |
| `cdp.Page.set_file_input_files` | `root.get("root", {}).get("nodeId")` | `deep_get(root, "root.nodeId")` | 0.0.11 |
| `probe.pending_dialogs` | `.get("params", {}).get("type", "dialog")` | `deep_get(item, "params.type", "dialog")` | 0.0.11 |

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

The predicate at `plan.safe_component` reads as a comparison rather than a test
because orval has no `has_control`. That is candidate C8; the comparison
allocates one string per component, which against a few thousand conversations
is nothing worth a hand-rolled regex to avoid.

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
way. Where they differ the new behaviour degrades better: `set_file_input_files`
now reaches its own `BrowserError(detail=f"no element matches {selector}")`
instead of an `AttributeError` that names neither the selector nor the call, and
`pending_dialogs` still reports that a dialog is open, under the generic label its
default already exists to supply, rather than failing the enumeration. A safety
listing that raises is worse than one that says `javascript:dialog`.

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
| `export.source`'s fingerprint → `hashify` | `hashify` hashes a `str` directly but **pickles** everything else. On bytes it returns the digest of a pickle. There is a comment at the call site saying so |
| `log.safe_token`'s bounded cut → `truncate` | D1 is fixed, so `truncate(v, limit, suffix="")` is now exactly `v[:limit]` — verified over every combination of four strings and five limits. The slice stays anyway: it needs no import to read, and `truncate` raises on `limit <= 0` where `safe_token(v, 0)` returns `(empty)`. A helper that turns a degenerate argument into an exception is not an improvement on a slice that cannot fail |
| `probe._expect_const`'s `[item for item in expect if item]` → `compact` | `compact(expect, none_only=False)` is equivalent for a `Sequence[str]`, but the comprehension carries a comment explaining *which* falsy value matters and why (`indexOf('')` is 0 on every string). `none_only=False` hides that behind a flag |
| Any `@timing` | It logs an f-string through `logging.getLogger("orval.utils")` — outside the `dataporter` logger, so past `ContentGuard`, and against this repo's rule that log messages are constants and variable data goes in `extra` |
| `runner`/`helpers` elapsed times → `pretty_duration` | `elapsed_s` and `elapsed_ms` are numeric fields in JSON-lines records, read by `19`'s parser and by `21`'s instruments. Nothing formats a duration for a human to read, so there is nothing to pretty-print |
| `config._describe` / `source._describe` | Genuinely duplicated, but shaped by pydantic's `ValidationError`. orval has no dependencies and should keep none |

## C. Candidates for orval

Each entry names the source it generalises from, so the proposed function has a
real caller to be checked against. **C1 and C2 shipped in 0.0.12** and are kept
here, struck through, so the list reads as a record rather than a wish.

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

### C5 — `orval.containers.unique(seq, key=None)`

*From `plan._distinct`, `source._collect_duplicates` and `model.Conversation._split`.*

Order-preserving deduplication. orval has `chunkify`, `flatten`, `compact` and
`is_empty` but no dedupe, which is the collection utility people reach for most, and
the one whose naive spelling (`set`) silently loses order. dataporter hand-rolls
three variants of it. `key` matters: `plan._distinct` deduplicates on either of two
keys, so a `key` returning a tuple, or accepting a callable per element, would be
worth designing rather than assuming.

### C6 — `orval.token_utils.chunk_text(text, budget, separator="\n\n")`

*From `render._split_paragraphs`.*

Split a string into pieces no longer than `budget`, preferring `separator`
boundaries and hard-cutting only a piece that is indivisible on its own. This is the
sibling `truncate_tokens` is missing: `truncate_tokens` throws the tail away, and
what anyone feeding long text to an LLM actually needs is every piece, in order. A
`chunk_tokens(text, budget)` measured with `estimate_tokens` follows from the same
implementation.

### C7 — ``orval.strings.fence(content, char="`", minimum=3)``

*From `render._fence_for`.*

The shortest fence that the content cannot close early: `max(minimum, longest run
of char in content + 1)`. Everyone embeds untrusted text in a fenced block and
almost nobody handles the escape, so the text spills into the surrounding document
as prose the moment somebody's message contains a fence of its own.

### C8 — `orval.strings.has_control(string)`

*From `plan.safe_component`.*

*New in this pass, and a direct consequence of C1 shipping.* `strip_control`
answers "give me this without control characters"; half its callers want "does
this contain one", which is a *rejection*, not a repair. `plan.safe_component`
refuses a path component outright rather than sanitising it — a repaired filename
names a different file, or none — so it now asks `strip_control(v) != v`, building
a string it throws away in order to compare it.

One line, `bool(_CONTROL_RE.search(string))`, reusing the pattern `strip_control`
already compiles. The same argument applies to `strip_styling`, whose zero-width
pattern has no predicate either; `has_control` and `has_styling` would be a pair.

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

### D3 — the `v0.0.12` tag points one commit before the version it names

*Release hygiene, not a code defect, and worth an issue on `lukin0110/orval`.*

`v0.0.12` points at `6e686f0`, whose `pyproject.toml` still reads
`version = "0.0.11"`. The bump is the next commit, `af19f8f`, which is not
tagged. So `git checkout v0.0.12 && uv build` produces a distribution labelled
0.0.11, and `pip install git+...@v0.0.12` installs something that reports the
previous version — which is exactly how a bug report ends up filed against the
wrong release.

The published artefact is fine: the three modules in the 0.0.12 wheel are
byte-identical to `origin/main` (sha256 over `strings.py`, `datetimes.py` and
`utils.py` matched), so everything reviewed above is what shipped. Only the tag
is misplaced, and moving it to `af19f8f` fixes it.
