.PHONY: lint check check-all fmt test test-all install

lint:
	uv run ruff check src tests spikes
	uv run ruff format --check src tests spikes
	uv run ty check --error-on-warning src spikes

# What a developer runs, and what CI runs on a pull request: lint, types, and the
# fast half of the suite. The slow half — anything that spawns a subprocess,
# binds a socket or launches a browser — is deselected by `addopts` in
# pyproject.toml. `15` is what made four minutes worth splitting; `22` is what
# made the other half quick, and the split stays as a safety rail rather than a
# necessity.
check: lint test

# Everything, plus the coverage gate. CI runs this on `main` after a merge, and
# it is the only command that measures coverage: `fail_under = 99` is checked
# here and nowhere else, so run it yourself before opening a pull request that
# adds a code path only the slow half exercises.
check-all: lint test-all

test:
	uv run pytest

# `-m "slow or not slow"` rather than `-m ""`: both clear the default selection,
# but only this one relies on the documented expression grammar, and it reads as
# "everything" to somebody who has not met the trick.
#
# `-n auto` here and not in `addopts`, which is `22`'s last item: the remaining
# minute is ~1300 tests each paying a subprocess or a socket, it divides by the
# core count almost exactly (72s serial, 22s across four), and it is the only
# saving left that removes no work. Out of `addopts` because a parallel run is a
# worse place to *debug* from — no live output, no `--pdb`, tracebacks arriving
# out of order — and the inner loop `addopts` serves is three seconds either way.
# A one-off can always ask: `uv run pytest -m "slow or not slow" -n auto`.
test-all:
	uv run pytest -m "slow or not slow" --cov --cov-report=term-missing -n auto

fmt:
	uv run ruff format src tests spikes
	uv run ruff check --fix src tests spikes

install:
	uv sync
