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
