"""`python -m dataporter`, for a caller who has the package but not the script.

The console script is `dataporter.cli:app` and this is the same object, called
the same way: one command surface reached by two spellings, and no second
argument parser to keep in step with the first. A host project that installed us
into its own environment runs `python -m dataporter doctor` without putting
anything on `PATH`, which is the case `25` exists for.

The guard below is excluded from coverage in `pyproject.toml` rather than
pretended about: it runs in a subprocess, where coverage does not follow it, and
`tests/test_packaging.py` is what proves the module works.
"""

from dataporter.cli import app

if __name__ == "__main__":
    app()
