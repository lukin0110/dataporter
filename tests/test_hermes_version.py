"""The version floor, and reading a version out of whatever Hermes prints."""

from dataporter.hermes import version as versioning


def test_a_bare_version_is_read() -> None:
    assert versioning.parse_version("0.4.2") == (0, 4, 2)


def test_decoration_around_the_version_is_ignored() -> None:
    """`hermes --version` has printed all three of these shapes at some point."""
    assert versioning.parse_version("hermes 0.4.2") == (0, 4, 2)
    assert versioning.parse_version("hermes-agent 1.0 (python 3.12.3)") == (1, 0)
    assert versioning.parse_version("v2.10.0-rc1\n") == (2, 10, 0)


def test_no_digits_at_all_is_unreadable() -> None:
    assert versioning.parse_version("command not found") is None


def test_the_floor_compares_numerically_not_lexically() -> None:
    """`0.10` is newer than `0.9`, which a string comparison gets wrong."""
    assert versioning.at_least((0, 10), (0, 9))
    assert not versioning.at_least((0, 9), (0, 10))


def test_missing_components_count_as_zero() -> None:
    assert versioning.at_least((0, 4), (0, 4, 0))
    assert not versioning.at_least((0, 4), (0, 4, 1))


def test_the_pinned_minimum_accepts_itself() -> None:
    assert versioning.at_least(versioning.MINIMUM_VERSION)


def test_format_round_trips() -> None:
    assert versioning.format_version((0, 4, 2)) == "0.4.2"
