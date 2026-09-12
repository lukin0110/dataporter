"""The error taxonomy.

Every failure this tool reports is one of the categories in the table in
`specs/impl/01-foundation.md`. Two properties matter downstream:

- `category` is a stable wire string. `06` stores it in `state.json`, `09` puts it
  in its result contract and `19` groups failures by it, so it is a `StrEnum` and
  its values never change.
- `transient` says whether retrying could plausibly help. It is a property of the
  *class*, not a judgement made where the error is raised, so that `13` and `19`
  can derive "retry recommended" without a per-call guess.

Three rows of the table — `ui`, `browser` and `verification` — are marked "per
instance": whether they are worth retrying genuinely depends on what happened. For
those, and only those, the raiser may pass `transient=`. Passing it anywhere else
is a `TypeError`, because that is exactly the per-call guess the design forbids.
Leaving it unset on a per-instance class yields `None`, meaning "unknown", which
`13` records as a null `retry_recommended` and `19` renders as `retry=unknown`.

`detail` is operator-facing and never contains conversation content: `19` prints it
verbatim into the report.
"""

from enum import StrEnum
from typing import ClassVar


class Category(StrEnum):
    """Failure categories. Values are stable on the wire."""

    AUTH = "auth"
    CAPTCHA = "captcha"
    SECURITY_CHALLENGE = "security_challenge"
    RATE_LIMIT = "rate_limit"
    GENERATION = "generation"
    NETWORK = "network"
    NAVIGATION = "navigation"
    DIALOG = "dialog"
    UI = "ui"
    BROWSER = "browser"
    HERMES = "hermes"
    EXPORT = "export"
    UNSUPPORTED = "unsupported"
    VERIFICATION = "verification"
    SAFETY = "safety"


class UsageError(Exception):
    """An operator-fixable contradiction in what was asked. Exit `2`.

    Not a `MigrationError`: nothing failed, and no category in the table names
    it. `23` added it so that the library can refuse two flags that cannot both
    be honoured — `--limit` above the ceiling without `--all`, a selection flag
    beside `--pilot`, an export path that is not there — from wherever the
    refusal is decided, and the CLI prints `error: <text>` and exits `2` for it
    exactly as it does for a `ConfigError`. The message is the whole of it.
    """


class StoreError(UsageError):
    """The store cannot be written as asked (`30`). Exit `2`.

    A stamp that already exists, an ask already open, no ask to abandon, a label
    or a source that is not one, a store that cannot be written to, a snapshot
    that never finished. Every one of them is the operator's to fix — by
    choosing a different label, by abandoning the ask, by removing a directory —
    which is what makes it a `UsageError` and not a row of `01`'s table.
    """


class FetchError(UsageError):
    """The link did not lead to this source's export (`30`). Exit `2`.

    Not `https`, refused by the vendor, expired, not a zip, not an export, over
    the byte cap, or a copy that did not match what was downloaded. Exit `2`
    rather than `6`: an expired link is fixed by asking again, and `6` sends an
    operator to `doctor` for a machine that is missing something.

    A detail never carries `str()` of an `HTTPError` or a `URLError`, both of
    which stringify the URL they failed on, and the link is a credential to the
    archive for as long as it lives (§32). Only `.code` and `.reason` ever reach
    a message.
    """


class MigrationError(Exception):
    """Base class. Abstract — raise one of the subclasses below."""

    category: ClassVar[Category]
    default_transient: ClassVar[bool | None] = None
    """The class answer to "is retrying worth it". `None` means "per instance"."""

    def __init__(
        self,
        *,
        detail: str = "",
        transient: bool | None = None,
        step: str | None = None,
        source_conversation_id: str | None = None,
    ) -> None:
        cls = type(self)
        if not hasattr(cls, "category"):
            raise TypeError(
                f"{cls.__name__} is abstract: raise a MigrationError subclass "
                f"that declares a category"
            )
        if transient is not None and cls.default_transient is not None:
            raise TypeError(
                f"{cls.__name__}.transient is fixed at {cls.default_transient} "
                f"by its category; do not decide it at the call site"
            )
        super().__init__(detail)
        self.detail = detail
        self.transient: bool | None = (
            transient if transient is not None else cls.default_transient
        )
        self.step = step
        """The last step name reached, one of `11`'s step names."""
        self.source_conversation_id = source_conversation_id


class AuthError(MigrationError):
    """Not signed in to the destination account. Needs a human."""

    category = Category.AUTH
    default_transient = False


class CaptchaError(MigrationError):
    """A CAPTCHA is in the way. Needs a human."""

    category = Category.CAPTCHA
    default_transient = False


class SecurityChallengeError(MigrationError):
    """An unexpected security challenge is in the way. Needs a human."""

    category = Category.SECURITY_CHALLENGE
    default_transient = False


class RateLimitError(MigrationError):
    """The destination account is rate limited."""

    category = Category.RATE_LIMIT
    default_transient = True

    def __init__(
        self,
        *,
        detail: str = "",
        retry_after_s: float | None = None,
        step: str | None = None,
        source_conversation_id: str | None = None,
    ) -> None:
        super().__init__(
            detail=detail, step=step, source_conversation_id=source_conversation_id
        )
        self.retry_after_s = retry_after_s


class GenerationError(MigrationError):
    """Claude's response failed to generate."""

    category = Category.GENERATION
    default_transient = True


class NetworkError(MigrationError):
    """A network call failed."""

    category = Category.NETWORK
    default_transient = True


class NavigationError(MigrationError):
    """The page went somewhere unexpected."""

    category = Category.NAVIGATION
    default_transient = True


class DialogError(MigrationError):
    """An unexpected dialog appeared."""

    category = Category.DIALOG
    default_transient = True


class UIError(MigrationError):
    """Composer missing, click failed, ambiguous state."""

    category = Category.UI
    default_transient = None


class BrowserError(MigrationError):
    """Chrome gone, CDP unreachable."""

    category = Category.BROWSER
    default_transient = None


class HermesError(MigrationError):
    """Hermes process failed, returned bad result JSON, or timed out."""

    category = Category.HERMES
    default_transient = True


class HermesUsageError(HermesError):
    """Hermes cannot be invoked as asked: not installed, too old, or it rejected
    the arguments (its own exit code `2`).

    Category `hermes` like its parent, but never worth retrying — the next attempt
    would make the same mistake at a later time. A subclass rather than a
    `transient=False` at the raise site, because `01`'s rule is that `transient`
    is a property of the class and not a judgement made where the error is raised;
    `09` needs one fixed `False` inside the `hermes` row, and this is the class
    that carries it.
    """

    default_transient = False


class ExportError(MigrationError):
    """The export archive is malformed."""

    category = Category.EXPORT
    default_transient = False


class UnsupportedError(MigrationError):
    """The export contains something this tool cannot migrate."""

    category = Category.UNSUPPORTED
    default_transient = False


class VerificationError(MigrationError):
    """A migrated conversation did not verify."""

    category = Category.VERIFICATION
    default_transient = None


class SafetyError(MigrationError):
    """An action outside the allowed surface was requested."""

    category = Category.SAFETY
    default_transient = False


ERROR_CLASSES: dict[Category, type[MigrationError]] = {
    cls.category: cls
    for cls in (
        AuthError,
        CaptchaError,
        SecurityChallengeError,
        RateLimitError,
        GenerationError,
        NetworkError,
        NavigationError,
        DialogError,
        UIError,
        BrowserError,
        HermesError,
        ExportError,
        UnsupportedError,
        VerificationError,
        SafetyError,
    )
}
"""Every category in the table, mapped to the class that carries it."""
