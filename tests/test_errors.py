"""The error taxonomy: one class per category, and the `transient` column."""

import pytest

from dataporter.errors import (
    ERROR_CLASSES,
    BrowserError,
    Category,
    MigrationError,
    NetworkError,
    RateLimitError,
    UIError,
    VerificationError,
)

# The `transient` column of the table in `specs/impl/01-foundation.md`.
# `None` is the "per instance" rows: transience is genuinely unknown until the
# raiser says so, and `13` records that as a null `retry_recommended`.
TRANSIENT_COLUMN: dict[Category, bool | None] = {
    Category.AUTH: False,
    Category.CAPTCHA: False,
    Category.SECURITY_CHALLENGE: False,
    Category.RATE_LIMIT: True,
    Category.GENERATION: True,
    Category.NETWORK: True,
    Category.NAVIGATION: True,
    Category.DIALOG: True,
    Category.UI: None,
    Category.BROWSER: None,
    Category.HERMES: True,
    Category.EXPORT: False,
    Category.UNSUPPORTED: False,
    Category.VERIFICATION: None,
    Category.SAFETY: False,
}

PER_INSTANCE = [UIError, BrowserError, VerificationError]


def test_every_category_has_a_class() -> None:
    assert set(ERROR_CLASSES) == set(Category)


def test_the_table_covers_every_category() -> None:
    assert set(TRANSIENT_COLUMN) == set(Category)


@pytest.mark.parametrize("category", list(Category), ids=lambda c: c.value)
def test_transient_column(category: Category) -> None:
    error = ERROR_CLASSES[category](detail="something happened")
    assert error.category is category
    assert error.transient is TRANSIENT_COLUMN[category]


@pytest.mark.parametrize("cls", PER_INSTANCE, ids=lambda c: c.__name__)
def test_per_instance_rows_accept_an_override(cls: type[MigrationError]) -> None:
    assert cls(detail="d", transient=True).transient is True
    assert cls(detail="d", transient=False).transient is False
    # Unset stays unknown rather than defaulting to a guess.
    assert cls(detail="d").transient is None


def test_fixed_rows_reject_a_call_site_guess() -> None:
    with pytest.raises(TypeError, match="fixed at True"):
        NetworkError(detail="d", transient=False)


def test_base_class_is_abstract() -> None:
    with pytest.raises(TypeError, match="abstract"):
        MigrationError(detail="d")


def test_categories_serialise_as_their_wire_strings() -> None:
    """`06` stores this in state.json and `19` groups by it."""
    assert Category.SECURITY_CHALLENGE == "security_challenge"
    assert f"{Category.RATE_LIMIT}" == "rate_limit"


def test_rate_limit_carries_retry_after() -> None:
    error = RateLimitError(detail="429", retry_after_s=30.0)
    assert error.retry_after_s == 30.0
    assert error.transient is True
    assert RateLimitError(detail="429").retry_after_s is None


def test_common_attributes() -> None:
    error = UIError(
        detail="composer missing",
        step="paste",
        source_conversation_id="abc-123",
        transient=False,
    )
    assert error.detail == "composer missing"
    assert error.step == "paste"
    assert error.source_conversation_id == "abc-123"
    # super().__init__(detail) was called, so the exception prints and pickles.
    assert str(error) == "composer missing"
    assert error.args == ("composer missing",)


def test_detail_is_keyword_only() -> None:
    """Positional construction would let `detail` slide into `transient`."""
    with pytest.raises(TypeError):
        NetworkError("timeout")  # type: ignore[misc]
