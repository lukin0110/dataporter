.PHONY: check fmt test install

# The one command CI runs. Keep them identical.
check:
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run ty check --error-on-warning src
	uv run pytest

fmt:
	uv run ruff format src tests
	uv run ruff check --fix src tests

test:
	uv run pytest

install:
	uv sync
