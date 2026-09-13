"""Signing in without a person (`24`).

Two halves, in order, and the order is the design:

1. **The agent brings the page to the form.** One Hermes task, in the shape of
   `20`'s follow-up probe: navigate to `https://claude.ai/login`, get past
   whatever banner or consent dialog is in the way, take the email path and
   never a Google, SSO or passkey one, and stop the moment an email or password
   field is showing. It types nothing. It reports what it found as one JSON
   object, `FormResult`, and that object never carries a credential because the
   agent was never given one.
2. **This process types into it.** `browser.login_form` reads which field is
   there, puts the credential in through CDP, presses Enter and looks again.
   The credential never enters the agent's process tree — not its environment
   (`hermes.client` builds one without it), not a helper it can run, not a
   file it can read — which is what makes "never through the model" true by
   construction rather than by instruction.

The agent's word never decides anything: after both halves the page is probed
again in this process, and `signed_in` is what `browser.session.signed_in`
says. What this module cannot do is finish a sign-in that asks for something
other than a password — an emailed code, a CAPTCHA, a challenge — and for those
it stops and says why, in `intervention`'s words, so that the run pauses (§12)
rather than guesses.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from dataporter import PROGRAM_NAME, log
from dataporter import intervention as intervening
from dataporter.browser import login_form
from dataporter.browser import session as browser_session
from dataporter.browser.launcher import BrowserSession
from dataporter.config import Credentials, Settings
from dataporter.errors import AuthError, HermesError, UsageError
from dataporter.hermes import prompt as prompting
from dataporter.hermes import runner as hermes_running

_logger = log.get_logger(__name__)

MISSING_CREDENTIALS = (
    "--non-interactive needs credentials: set DATAPORTER_AUTH__EMAIL and "
    "DATAPORTER_AUTH__PASSWORD, or pass --email and --password-file"
)
"""Exit `2`, before any browser starts: a run that would stop at the first
sign-in form is a run that should not have started."""

NEEDS_PERSON = "automatic sign-in stopped: {reason} — run: {program} login"
"""Exit `3`, when the sign-in could not be completed and nothing had begun.
The reason is one of `intervention.REASON_PHRASES`, or `hermes failed`."""

HERMES_FAILED = "hermes failed"

RUN_ID = "signin-{attempt}"

FORM_READY = "form_ready"
OUTCOMES = (FORM_READY, "needs_human", "failed")


class FormResult(BaseModel):
    """What the agent's half reports: the form is there, or why it is not.

    `fields` names what was showing, `url` where. `needs_human_reason` is one of
    `09`'s six; a code prompt with no password field is `auth_required`, because
    that is what it is — the page wants an authentication step this tool cannot
    supply. Never a value: the agent has none to report.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    outcome: Literal["form_ready", "needs_human", "failed"]
    fields: list[Literal["email", "password"]] = []
    url: str = ""
    needs_human_reason: str | None = None
    error: str = ""


HEAD = (
    "Use the skill `claude-migrate` (load it with skill_view before acting). This is\n"
    "a sign-in and not a migration: bring the attached browser's claude.ai tab to the\n"
    "sign-in form and stop. You type nothing into it.\n"
)

TAIL = """\
Procedure, in this order, verifying each step as the skill's sign-in section says:
browser_navigate to the login url; take one browser_snapshot; if a cookie or consent
banner is in the way, dismiss it with its own close or accept control, once; if the page
offers several ways to sign in, choose the one that asks for an email address — never
Google, Apple, SSO or a passkey; stop the moment an input for an email address or a
password is visible.

You hold no credentials and must not ask for any. Do not type into any field, do not
submit the form, and do not click anything labelled sign up, create, delete or upgrade.
A page asking for a code with no password field, a CAPTCHA, a puzzle or a security
challenge is `needs_human` with the matching reason.

Print exactly one JSON object as the last thing you output, and nothing after it:
{"outcome": "form_ready", "fields": ["email"], "url": "<the tab's url>"}
`fields` lists the inputs you saw, from `email` and `password`. `outcome` is
`form_ready`, `needs_human` or `failed`; `needs_human` carries `needs_human_reason`,
and `failed` carries `error` saying what stopped it, in your own words.
"""


def prompt(*, workspace: Path) -> str:
    """Return the sign-in task. Names a URL and the helper prefix; carries no credential."""
    return "\n".join([
        HEAD,
        f"login url: {login_form.LOGIN_URL}",
        f"helper: {prompting.helper_command(workspace)}",
        "",
        TAIL,
    ])


def require_credentials(settings: Settings) -> Credentials:
    """Both halves of `auth`, or the usage error that says which to set."""
    found = settings.credentials
    if found is None:
        raise UsageError(MISSING_CREDENTIALS)
    return found


@dataclass(frozen=True)
class SignInOutcome:
    """Signed in, or the reason a person is needed, in §12's words."""

    signed_in: bool
    reason: str | None = None
    detail: str = ""
    filled: Sequence[str] = ()


def _describe(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(item) for item in error['loc']) or '(root)'}: {error['msg']}" for error in exc.errors()
    )


def _phrase(reason: str | None) -> str:
    return intervening.REASON_PHRASES.get(reason or "", intervening.REASON_PHRASES[intervening.DEFAULT_REASON])


BLOCKED_REASONS: dict[str, str] = {
    login_form.CODE_OR_CHALLENGE: intervening.AUTH_REQUIRED,
    login_form.NO_FORM: intervening.AUTH_REQUIRED,
    login_form.NO_PROGRESS: intervening.AUTH_REQUIRED,
    login_form.NO_TAB: "browser_error",
    login_form.FIELD_NOT_FOCUSED: intervening.DEFAULT_REASON,
}
"""Why the deterministic half stopped, as the `needs_human` reason it is.

Everything the form did not take is `auth_required`: the account wants a step
this tool cannot make, and a person can. A tab that is gone is the browser's
fault, and a field that will not take focus is a page nobody here understands.
"""


class SignIn:
    """The two halves, run in order, for one browser session."""

    def __init__(self, settings: Settings, *, runner: hermes_running.HermesRunner | None = None) -> None:
        self.settings = settings
        self.runner = runner if runner is not None else hermes_running.HermesRunner(settings)
        self.attempts = 0

    def perform(self, session: BrowserSession) -> SignInOutcome:
        """Sign the session in, or say what a person would have to do."""
        credentials = require_credentials(self.settings)
        self.attempts += 1
        try:
            form = self._form()
        except HermesError as exc:
            _logger.warning("sign-in agent failed", extra={"attempt": self.attempts})
            return SignInOutcome(signed_in=False, reason=HERMES_FAILED, detail=exc.detail or HERMES_FAILED)
        if form.outcome != FORM_READY:
            reason = form.needs_human_reason if form.outcome == "needs_human" else intervening.DEFAULT_REASON
            _logger.info(
                "sign-in form not reached",
                extra={"outcome": form.outcome, "reason": reason or ""},
            )
            return SignInOutcome(signed_in=False, reason=_phrase(reason), detail=form.error)
        result = login_form.fill_and_submit(session, credentials, timeout_s=self.settings.timeouts.signin_s)
        signed_in = result.signed_in and browser_session.signed_in(session)
        _logger.info(
            "sign-in",
            extra={
                "signed_in": signed_in,
                "fields": len(result.filled),
                "blocked": result.blocked or "",
            },
        )
        if signed_in:
            return SignInOutcome(signed_in=True, filled=result.filled)
        blocked = result.blocked or login_form.NO_PROGRESS
        return SignInOutcome(
            signed_in=False,
            reason=_phrase(BLOCKED_REASONS.get(blocked, intervening.DEFAULT_REASON)),
            detail=blocked,
            filled=result.filled,
        )

    def _form(self) -> FormResult:
        """Return the agent's half: the subprocess, and the object it printed last."""
        raw = self.runner.run_raw(
            prompt(workspace=self.settings.workspace),
            run_id=RUN_ID.format(attempt=self.attempts),
            timeout_s=self.settings.timeouts.hermes_check_s,
        )
        payload = hermes_running.last_result_object(raw.stdout)
        if payload is None:
            raise HermesError(detail=f"no result json; stdout: {raw.stdout_path}")
        try:
            return FormResult.model_validate(payload)
        except ValidationError as exc:
            raise HermesError(detail=f"invalid sign-in json: {_describe(exc)}; stdout: {raw.stdout_path}") from exc


def needs_person(outcome: SignInOutcome) -> str:
    """Return the exit-`3` message for a sign-in that could not be completed."""
    return NEEDS_PERSON.format(reason=outcome.reason, program=PROGRAM_NAME)


def ensure_signed_in(
    settings: Settings,
    session: BrowserSession,
    *,
    signer: SignIn | None = None,
) -> bool:
    """Ensure the session is signed in, or raise `AuthError` (exit `3`).

    Interactively that is `12`'s rule unchanged: a signed-out session ends the
    run with `login` as the remedy. Unattended, one sign-in is attempted first,
    and the remedy named when it fails is still `login` — a person at a
    keyboard is what the form wanted. `True` when this call did the signing in,
    so that a run can count it.
    """
    if browser_session.signed_in(session):
        return False
    if not settings.non_interactive:
        raise AuthError(detail=browser_session.SIGNED_OUT)
    outcome = (signer if signer is not None else SignIn(settings)).perform(session)
    if not outcome.signed_in:
        raise AuthError(detail=needs_person(outcome))
    return True
