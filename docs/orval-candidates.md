# orval and dataporter

[orval](https://github.com/lukin0110/orval/) has been a declared dependency since
`266ef93` and was imported nowhere. This file records what it now replaces, what it
must never replace, and what dataporter has written that belongs upstream in it.

Everything below was checked against **orval 0.0.11** by reading its source and
running the functions in question. A claim that a swap is byte-identical means it
was executed, not inferred.

## A. Adopted

| Site | Was | Now |
| --- | --- | --- |
| `log.strict_by_default` | `os.environ.get(...) not in ("", "0")` | `to_bool(..., default=False)` |
| `seed.sha256_of` | `hashlib.sha256(text.encode("utf-8")).hexdigest()` | `hashify(text)` |
| `log.run_log_path` | `datetime.now(UTC)` | `utcnow()` |

**`to_bool` is a behaviour change, and the only user-visible one here.** Under the
old expression `DATAPORTER_LOG_STRICT=false` turned the content guard's strict mode
*on*, as did `no`, `off` and every typo — anything non-empty that was not the single
character `0`. It now reads the spellings `to_bool` recognises (`1`, `true`, `yes`,
`y`, `t`, `on`, case-insensitively) and treats everything else, unrecognised values
included, as off. Nothing contradicted this: `specs/impl/01-foundation.md` does not
pin the variable and no test touched it. `tests/test_log.py` now does.

**`hashify` of a `str` is sha256 over `str.encode()`, which is UTF-8** — the same
digest `sha256_of` always returned, confirmed by running both. The golden files
under `tests/fixtures/seeds/` did not move. The wrapper function stays, because
`08`'s paste helper and the tests name it, and
`test_sha256_of_is_sha256_over_utf8_bytes` pins the digest to its definition rather
than to orval's continued agreement: this value is compared against what a browser
composer holds, and a change upstream would fail every paste for a reason nobody
could see from the failure.

`log.CONTROL_CHARACTERS` is not an orval change but was found looking for one:
`re.compile(r"[\x00-\x1f\x7f]")` was compiled once in `log.py` and again in
`plan.py`. It is now compiled once and public. See candidate C1 — orval is where
it should eventually live.

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
| `log.safe_token`'s bounded cut → `truncate` | See defect D1: `truncate` returns strings longer than the limit it was given |
| `config.bootstrap_workspace` → `coalesce_lazy` | See defect D2: `ty --error-on-warning` rejects it. Tried, reverted, reason recorded in the docstring |
| Any `@timing` | It logs an f-string through `logging.getLogger("orval.utils")` — outside the `dataporter` logger, so past `ContentGuard`, and against this repo's rule that log messages are constants and variable data goes in `extra` |
| `config._describe` / `source._describe` | Genuinely duplicated, but shaped by pydantic's `ValidationError`. orval has no dependencies and should keep none |

## C. Candidates for orval

Seven things in this repo are general-purpose, pure Python and dependency-free.
Two of them dataporter had already written twice. Each entry names the source it
generalises from, so the proposed function has a real caller to be checked against.

### C1 — `orval.strings.strip_control(string, replacement="")`

*From `log.safe_token` and `plan.safe_component` (`log.py`, `plan.py`).*

Remove or replace `[\x00-\x1f\x7f]`. A name, an id or a reason read out of somebody
else's file may legally contain a newline; put one in a log line and it becomes two
records, put one in terminal output and it forges a line. dataporter needs the same
set twice for two different reasons and now shares one constant. It sits beside the
existing `strip_styling`, which already compiles a zero-width-character regex for
the same family of problem, and beside `strip_accents`.

### C2 — `orval.datetimes.to_utc(value, *, assume_utc=True)`

*From `export/model._utc`.*

Naive → attach UTC; aware → `astimezone(UTC)`. `orval.datetimes` currently holds
`utcnow()` alone, and this is its obvious companion: the reason `utcnow()` exists —
that the stdlib hands out naive datetimes — is the reason every codebase eventually
writes this normaliser. `assume_utc=False` would raise on a naive value, for callers
who would rather fail than guess.

### C3 — `orval.datetimes.iso_utc(value, timespec="milliseconds")`

*From `log.JsonlFormatter.format`.*

`value.isoformat(timespec=...).replace("+00:00", "Z")`. Every JSON-lines logger
writes this line, and the `replace` is the part people forget, so the field ends up
in two spellings across one file.

### C4 — `orval.paths.is_safe_component(name)` and `is_within(root, candidate)`

*From `plan.safe_component` and `plan._within`.*

A new module. `is_safe_component` answers "is this one ordinary path component" —
non-empty, not `.` or `..`, no separator, no control character. `is_within` answers
"does this really sit under that root once symlinks resolve". Both guard the same
mistake: joining a name from an untrusted file to a path. Both are copy-pasted into
every project that reads someone else's archive, and both are easy to get subtly
wrong — `plan._locate` records the *resolved* path rather than the name that led to
it, precisely so a symlink cannot be swapped between the check and the read.

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

### Considered and rejected as too specific to this project

`summary.totals_lines` and `_breakdown_lines` (the width rule is the brief's §9, not
a general one), `source._token`, `render.format_timestamp`, `seed.part_filename`,
and `render.normalise` — one stdlib call, and `strip_accents` already normalises
internally.

## D. Defects found in orval 0.0.11

Both are worth an issue on `lukin0110/orval`. Both were confirmed by running them.

### D1 — `truncate` returns strings longer than the limit it was given

```python
truncate("hello world", 8)   # 'hello w...' — ten characters, for a limit of eight
truncate("abcdef", 3, "")    # 'ab' — two characters, for a limit of three
```

`strings.py` slices `string[: number - 1]` and then appends the suffix, so the
result is `number - 1 + len(suffix)` characters. It should almost certainly be
`string[: number - len(suffix)]`, which makes the limit an actual bound and makes
an empty suffix mean a plain cut. The current behaviour also depends on the suffix
being exactly three characters to be even approximately right.

This is why `log.safe_token`'s `[:limit]` was left alone: it needs a hard bound with
no ellipsis, and neither of `truncate`'s behaviours supplies one.

### D2 — `coalesce` / `coalesce_lazy` are unusable under a strict type checker

Both are typed `-> T | None` unconditionally, even when the final argument cannot be
`None` — which is the config-fallback chain the docstrings advertise. So:

```python
def bootstrap_workspace(workspace: Path | None = None) -> Path:
    return coalesce_lazy(lambda: workspace, from_env, lambda: DEFAULT_WORKSPACE)
```

fails `ty check --error-on-warning` with `invalid-return-type: expected Path, found
Path | None`. The call site's options are a `cast`, an `assert`, or a suppression
comment, all of which cost more than the four lines the helper replaced — so this
repo kept the explicit form and said why in the docstring.

An `@overload` whose last parameter is `T` rather than `T | None`, returning `T`,
would fix it and would cover the documented use exactly.
