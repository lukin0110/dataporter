"""Q3's ladder: what the real composer does with 5 k to 200 k characters.

Not product code. It drives `hermes-claude-migrate browser paste` — the same
command Hermes runs — at five sizes against both paste methods, reads the
composer back with `browser probe`, and writes the table `docs/seed-limits.md`
is waiting for.

It never submits. A round is: check the composer is empty, paste, read it back,
ask the human the one thing only a human can see (did the UI turn the insert into
a "pasted text" attachment), then ask them to clear the composer. So the account
gains no conversations and the run costs no quota, which is why Q3 can be
answered before the riskier questions are.

    uv run python spikes/paste_ladder.py --workspace migration

Preconditions, all of them from `spikes/README.md`: a Chrome launched by
`hermes-claude-migrate login`, signed in to the **throwaway** destination
account, sitting on exactly one claude.ai tab at `/new`.
"""

import argparse
import dataclasses
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import spike

DEFAULT_SIZES = (5_000, 20_000, 50_000, 100_000, 200_000)
DEFAULT_METHODS = ("insert_text", "exec_command")

CLI = "hermes-claude-migrate"
HELPER_TIMEOUT_S = 300.0

TEXT_MISMATCH = "text_mismatch"
"""The one `08` failure code that still means the insert happened.

`paste` answers `ok` when the composer came back holding the seed, and
`text_mismatch` when it came back holding something else — both are Q3
measurements, and the second is the more interesting one. Every other code it
can answer with (`composer_not_empty`, `composer_missing`, `no_claude_tab`,
`seed_unreadable`, ...) means the seed never reached the composer, so the round
watched nothing and has nothing to say about a "pasted text" chip.
"""

_UNKNOWN = spike.UNKNOWN


# --------------------------------------------------------------------------- #
# The sample text
# --------------------------------------------------------------------------- #

_BLOCK = """\
## Human — 2024-03-0{day}T09:{minute:02d}:00Z

Block {index}. This is filler with the shape of a rendered conversation: a
heading, a paragraph that wraps, a line with a leading space and a blank line
between turns, because those are the three things `normalise` and `blockText`
disagree about when they disagree.
 An indented line, to see whether the leading space comes back as U+00A0.

## Assistant — 2024-03-0{day}T09:{minute:02d}:30Z

Acknowledged block {index}.

"""
"""Our own text, never the account's. `10` records lengths and digests; nothing
that reaches `docs/spike/` should be something a person wrote."""


def sample(chars: int) -> str:
    """Deterministic filler of about `chars` characters, ending on a real one.

    Truncated to the last non-whitespace character before the limit and given
    one trailing newline, the shape `04` writes: `paste` compares normalised
    text, and `normalise` strips trailing whitespace, so a sample ending in a
    half-written blank line would measure the comparison rather than the
    composer. The ladder records the file's real length, not the size asked for.
    """
    parts: list[str] = []
    total = 0
    index = 0
    while total < chars:
        index += 1
        block = _BLOCK.format(index=index, day=index % 9 + 1, minute=index % 60)
        parts.append(block)
        total += len(block)
    return "".join(parts)[: chars - 1].rstrip() + "\n"


# --------------------------------------------------------------------------- #
# Talking to our own CLI
# --------------------------------------------------------------------------- #


def helper(command: str, workspace: Path, *args: str) -> dict[str, Any]:
    """One `browser` helper, as its JSON object.

    The helpers print exactly one object and use the exit code for pass or fail,
    so a non-zero exit is read, not raised: a refusal (`composer_not_empty`, say)
    is data the ladder wants to record.
    """
    finished = subprocess.run(
        [command, "--workspace", str(workspace), "browser", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=HELPER_TIMEOUT_S,
        check=False,
    )
    line = (finished.stdout or "").strip().splitlines()
    try:
        parsed = json.loads(line[-1]) if line else {}
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    parsed.setdefault("ok", finished.returncode == 0)
    if not line:
        parsed["stderr"] = (finished.stderr or "").strip()[:500]
    return parsed


def ask(question: str, *, prompt: bool) -> str:
    """One yes/no the page can be looked at for. `unknown` when unattended."""
    if not prompt:
        return _UNKNOWN
    answer = input(f"{question} [y/n/?] ").strip().lower()
    return {"y": "yes", "n": "no"}.get(answer, _UNKNOWN)


def pause(message: str, *, prompt: bool) -> None:
    if prompt:
        input(f"{message} — press Enter when done. ")


# --------------------------------------------------------------------------- #
# One rung
# --------------------------------------------------------------------------- #


def round_trip(
    command: str, workspace: Path, seed: Path, method: str, *, prompt: bool
) -> dict[str, Any]:
    """Paste one sample once, and report everything that can be measured."""
    before = helper(command, workspace, "probe")
    text = seed.read_text(encoding="utf-8")
    row: dict[str, Any] = {
        "chars": len(text),
        "method": method,
        "seed": seed.name,
        "composer_empty_before": before.get("composer_chars"),
        "composer_present": before.get("composer_present"),
    }
    if not before.get("composer_present"):
        row["skipped"] = "no composer — is the tab on /new and signed in?"
        return row

    pasted = helper(
        command, workspace, "paste", "--seed", str(seed), "--method", method
    )
    after = helper(command, workspace, "probe")
    # A refusal is not a measurement. Asking a human whether a chip appeared for
    # a round that never inserted anything files their guess as an observation,
    # and `table` would then mark it `observed on <date>`.
    inserted = bool(pasted.get("ok")) or pasted.get("error") == TEXT_MISMATCH
    row.update(
        {
            "inserted": inserted,
            "verbatim": bool(pasted.get("ok")),
            "error": pasted.get("error"),
            "paste_chars": pasted.get("chars"),
            "observed_chars": pasted.get("observed_chars"),
            "elapsed_ms": pasted.get("elapsed_ms"),
            "composer_chars_after": after.get("composer_chars"),
        }
    )
    if inserted:
        row["chip"] = ask("Did a 'pasted text' attachment appear?", prompt=prompt)
    # Unconditional: a round refused with `composer_not_empty` is precisely one
    # whose composer still needs clearing before the next.
    pause("Clear the composer (select all, delete)", prompt=prompt)
    return row


# --------------------------------------------------------------------------- #
# The table
# --------------------------------------------------------------------------- #

_COLUMNS = (
    "Chars",
    "Method",
    "Verbatim",
    "Composer chars read back",
    "Elapsed ms",
    "Chip",
    "Mark",
)
_HEADER = (
    "| " + " | ".join(_COLUMNS) + " |",
    "| " + " | ".join("-" * len(name) for name in _COLUMNS) + " |",
)
"""The header of `docs/seed-limits.md`'s ladder table, built from the column names
so that the rule row cannot drift out of alignment with them."""


def verdict(row: dict[str, Any]) -> str:
    """The `Verbatim` cell: what this round actually established.

    A bare `no` would read as "the composer mangled the seed" for a round that
    was refused before the seed ever got there, which is the opposite finding.
    """
    if "skipped" in row:
        return "skipped"
    if not row.get("inserted"):
        return f"refused ({row.get('error') or 'unknown'})"
    return "yes" if row["verbatim"] else "no"


def table(rows: list[dict[str, Any]], today: str) -> str:
    """The rows as the markdown `docs/seed-limits.md` holds, ready to paste."""

    def cell(value: Any) -> str:
        return "—" if value is None else str(value)

    lines: list[str] = list(_HEADER)
    for row in rows:
        # One rule for the mark: a row is an observation exactly when the seed
        # reached the composer. `tests/test_spike_docs.py` reads these marks, and
        # a row marked `observed` for a round that inserted nothing would tell it
        # the spike had run.
        observed = bool(row.get("inserted"))
        lines.append(
            "| {chars} | `{method}` | {verbatim} | {read_back} | {elapsed} "
            "| {chip} | {mark} |".format(
                chars=f"{row['chars']:,}".replace(",", " "),
                method=row["method"],
                verbatim=verdict(row),
                read_back=cell(row.get("composer_chars_after")),
                elapsed=cell(row.get("elapsed_ms")),
                chip=cell(row.get("chip")),
                mark=f"*observed on {today}*" if observed else "*unknown*",
            )
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("migration"))
    parser.add_argument("--command", default=CLI, help=f"defaults to `{CLI}`")
    parser.add_argument(
        "--sizes",
        default=",".join(str(size) for size in DEFAULT_SIZES),
        help="character counts to try, comma separated",
    )
    parser.add_argument(
        "--methods", default=",".join(DEFAULT_METHODS), help="comma separated"
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help=(
            "never ask the human anything. Only the first round is measured: "
            "clearing the composer between rounds is a human step"
        ),
    )
    args = parser.parse_args(argv)

    command = shutil.which(args.command)
    if command is None:
        parser.error(f"not on PATH: {args.command} (try `uv run`)")

    prompt = not args.no_prompt
    sizes = [int(item) for item in args.sizes.split(",") if item.strip()]
    directory = args.workspace / "spike"
    directory.mkdir(parents=True, exist_ok=True)

    context = spike.Context.read()
    methods = [item.strip() for item in args.methods.split(",") if item.strip()]
    if not prompt and len(sizes) * len(methods) > 1:
        # Nothing in `08` clears a composer, so between rounds only a human can.
        # Unattended, round two meets round one's text and every round after the
        # first is refused with `composer_not_empty` — honestly marked `unknown`
        # by `table`, but a ladder of one rung. Said here rather than discovered
        # at the bottom of a table.
        print(
            "warning: --no-prompt measures only the first round; the composer is "
            "never cleared, so the rest will be refused as `composer_not_empty`",
            file=sys.stderr,
        )
    rows: list[dict[str, Any]] = []
    for method in methods:
        for size in sizes:
            seed = directory / f"sample-{size}.txt"
            seed.write_text(sample(size), encoding="utf-8")
            row = round_trip(command, args.workspace, seed, method, prompt=prompt)
            rows.append(row)
            print(json.dumps(row, sort_keys=True), flush=True)

    today = context.recorded_at[:10]
    payload = {
        "context": dataclasses.asdict(context),
        "rows": rows,
        "table": table(rows, today),
    }
    out = spike.NOTES.parent / "paste-ladder.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    measured = [row for row in rows if "skipped" not in row]
    spike.record(
        "Q3",
        f"paste ladder: {len(measured)} of {len(rows)} rounds reached the composer",
        rounds=len(rows),
        measured=len(measured),
    )

    print(f"\n{payload['table']}\n\nwritten: {out}")
    print("Paste the table into docs/seed-limits.md and answer Q3 there.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
