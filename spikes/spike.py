"""Shared machinery for `10`'s spike: versions, timestamps, and a note file.

Nothing here is product code. `pyproject.toml` excludes `spikes/` from the sdist
and the wheel packages only `src/dataporter`, so this tree exists for the two
working days `10` is time-boxed to and for whoever repeats it after a UI change.

`10`'s method says every observation is a note with a UTC timestamp, the Hermes
version and the Chrome version. Written by hand that is three things to forget;
written here it is one command:

    uv run python spikes/spike.py note Q4 "Stop button is aria-label='Stop response'"

The note goes to `docs/spike/notes.jsonl`, one JSON object per line, and the two
versions are read off the installed binaries rather than typed.
"""

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from orval import utcnow

from dataporter.browser import launcher
from dataporter.errors import BrowserError
from dataporter.hermes import version as versioning

REPO = Path(__file__).resolve().parents[1]
NOTES = REPO / "docs" / "spike" / "notes.jsonl"

QUESTIONS = tuple(f"Q{number}" for number in range(1, 11))
"""`10`'s ten questions. A note against anything else is a typo, and a typo is how
an observation ends up in no document."""

UNKNOWN = "unknown"

_VERSION_TIMEOUT_S = 20.0


def _version_of(executable: Path | str) -> str:
    """`<executable> --version`, reduced to its first version number.

    Never raises: a spike note is worth recording even from a machine where one
    of the two binaries answers something unexpected.
    """
    found = shutil.which(str(executable))
    if found is None:
        return UNKNOWN
    try:
        finished = subprocess.run(
            [found, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=_VERSION_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN
    text = (finished.stdout or "") + (finished.stderr or "")
    parsed = versioning.parse_version(text)
    return versioning.format_version(parsed) if parsed is not None else UNKNOWN


def chrome_executable() -> str:
    """The browser `07` would launch, or `unknown`."""
    try:
        return str(launcher.find_executable())
    except BrowserError:
        return UNKNOWN


@dataclass(frozen=True)
class Context:
    """What every observation is stamped with."""

    recorded_at: str
    hermes_version: str
    chrome_version: str
    chrome_executable: str

    @classmethod
    def read(cls) -> "Context":
        chrome = chrome_executable()
        return cls(
            recorded_at=utcnow().isoformat(),
            hermes_version=_version_of("hermes"),
            chrome_version=UNKNOWN if chrome == UNKNOWN else _version_of(chrome),
            chrome_executable=chrome,
        )


def record(question: str, note: str, **fields: object) -> dict[str, object]:
    """Append one observation to `docs/spike/notes.jsonl` and return it."""
    if question not in QUESTIONS:
        raise SystemExit(f"not one of {QUESTIONS}: {question}")
    entry: dict[str, object] = {
        "question": question,
        "note": note,
        **asdict(Context.read()),
        **fields,
    }
    NOTES.parent.mkdir(parents=True, exist_ok=True)
    with NOTES.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    note = sub.add_parser("note", help="record one observation")
    note.add_argument("question", choices=QUESTIONS)
    note.add_argument("note", help="what was seen. No message content, no titles.")

    sub.add_parser("context", help="print the timestamp and versions and exit")

    args = parser.parse_args(argv)
    if args.command == "context":
        print(json.dumps(asdict(Context.read()), indent=2, sort_keys=True))
        return 0
    print(json.dumps(record(args.question, args.note), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
