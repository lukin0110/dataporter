"""A stand-in for `dataporter`, pointed at the fixture server.

`10`'s paste ladder drives our own CLI as a subprocess — the same command Hermes
runs — so the only way to exercise it without a claude.ai account is to give it a
command that speaks the same argv contract against a local page.

That contract is narrow and stable:

    <command> --workspace <path> browser probe
    <command> --workspace <path> browser paste --seed <path> --method <name>

so the shim below implements exactly those two, calling the real
`helpers.probe_page` and `helpers.paste_seed` with a `Surface` moved to the
fixture server. Everything the ladder is being tested on — the subprocess
boundary, the one-JSON-object contract, the exit code, the refusal codes — is
therefore real; only the host is not.

This fakes the *binary*, the way `fake_hermes.py` does, rather than patching
`subprocess`: the ladder resolves its command with `shutil.which`, and a test
that patched that away would stop testing the thing that breaks.
"""

import os
import stat
import sys
from pathlib import Path

from dataporter import PROGRAM_NAME

SHIM_NAME = PROGRAM_NAME
"""The shim's file name, which is what `prompt.helper_command()` tells the agent
to run: read from the package so the two cannot disagree."""

SHIM_SOURCE = "ladder_shim.py"
"""The Python behind the shim. A name that is not the package's, because the
shim's directory is `sys.path[0]` when it runs (see `write_shim`)."""

_SOURCE = """\
import argparse
import re
import sys
from pathlib import Path

from dataporter.browser import helpers
from dataporter.config import BrowserSettings, Settings, TimeoutSettings

CDP_PORT = {cdp_port}
SERVER_PORT = {server_port}

SURFACE = helpers.Surface(
    host="127.0.0.1",
    allowed=re.compile(
        r"^http://127\\.0\\.0\\.1:%d/(new|chat/[0-9a-f-]{{36}})(\\?.*)?$" % SERVER_PORT
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    sub = parser.add_subparsers(dest="group", required=True)
    browser = sub.add_parser("browser").add_subparsers(dest="verb", required=True)
    browser.add_parser("probe")
    paste = browser.add_parser("paste")
    paste.add_argument("--seed", type=Path, required=True)
    paste.add_argument("--method", default="insert_text")
    paste.add_argument("--append", action="store_true")
    args = parser.parse_args()

    settings = Settings(
        workspace=args.workspace,
        browser=BrowserSettings(cdp_port=CDP_PORT),
        timeouts=TimeoutSettings(cdp_call_s=30.0),
    )
    if args.verb == "probe":
        emission = helpers.run(
            settings,
            "probe",
            lambda client, config: helpers.probe_page(client, config, surface=SURFACE),
        )
    else:
        emission = helpers.run(
            settings,
            "paste",
            lambda client, config: helpers.paste_seed(
                client,
                config,
                seed=args.seed,
                method=helpers.PasteMethod(args.method),
                append=args.append,
                surface=SURFACE,
            ),
        )
    print(emission.text)
    return int(emission.exit_code)


if __name__ == "__main__":
    sys.exit(main())
"""


def write_shim(directory: Path, *, cdp_port: int, server_port: int) -> Path:
    """Write an executable shim into `directory` and return its path.

    The directory is what a caller puts on `PATH`; the ladder finds the command
    with `shutil.which`, exactly as it would find the installed console script.
    """
    directory.mkdir(parents=True, exist_ok=True)
    # Not `f"{SHIM_NAME}.py"`: Python puts a script's own directory first on
    # `sys.path`, so a source file named `dataporter.py` beside the shim *is* the
    # `dataporter` the shim then tries to import — "'dataporter' is not a
    # package", one probe answering nothing, and every ladder round skipped as
    # "no composer". The old name never collided because the command was not the
    # package; ADR 0004 made them the same word.
    script = directory / SHIM_SOURCE
    script.write_text(
        _SOURCE.format(cdp_port=cdp_port, server_port=server_port), encoding="utf-8"
    )
    shim = directory / SHIM_NAME
    shim.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8"
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return shim


def on_path(directory: Path) -> str:
    """`PATH` with `directory` in front."""
    return os.pathsep.join([str(directory), os.environ.get("PATH", "")])
