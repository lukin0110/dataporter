.PHONY: check fmt test install

# The one command CI runs. Keep them identical.
check:
	uv run ruff check src tests spikes
	uv run ruff format --check src tests spikes
	uv run ty check --error-on-warning src spikes
	uv run pytest

fmt:
	uv run ruff format src tests spikes
	uv run ruff check --fix src tests spikes

test:
	uv run pytest

install:
	uv sync
