"""The extraction protocol (`46`, brief `06` §68): both mocks, seeded, reconciled, traced.

`run.py` is the full run's protocol against the mock claude.ai. This is the
other protocol the same runner can drive: an extraction, by the shipped tool,
against each site's mock — `login`, an ask, the link read from the mock's
listing where the inbox would be, the fetch, a second ask and a second fetch,
`snapshots`, `session status`, `logout` — and the reconciliation of
what the tool filed with what the mock counted.

Three things are this protocol's own:

- **The account is seeded first.** A fresh mock holds no chats, and a snapshot
  of nothing proves only the flow. So the runner signs in to the mock through
  its own HTTP routes and posts a few chats and one upload, the way a person
  with the mock's walk would; the numbers the criteria check are then known
  before the tool starts. That sign-in is the mock's to count, and the
  reconciliation says so rather than subtracting it silently.
- **The link is masked everywhere the runner writes.** The mock prints it and
  lists it; the runner reads it, hands it to the tool on a command line, and
  records the step with `<link>` in its place. §66 is the tool's rule and this
  is the runner's copy of it, and the last criterion greps for the token.
- **No scripted agent is needed for either half.** §61's walk is the tool's
  own, and the mock claude.ai's sign-in is brief 07's two commands (`49`):
  `login` in the background, the runner playing the person at the window
  (`rehearsal.person`), the link read from the listing that stands in for the
  inbox, `login --link` from what stands for the other terminal. The `hermes`
  on the path is written all the same, for `setup`.

Both mocks are separate processes the operator starts, as `run.py`'s is; both
have to be fresh, since the ledger is the whole of the witness.
"""

import base64
import hashlib
import http.cookiejar
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rehearsal import run as running
from rehearsal.hermes import write_executable

ACCOUNT = "rehearsal"
"""The label both source accounts get. Not the login, as brief 03 §33 says."""

CHATGPT_PORT = 8444
EXPORTS_JSON_PATH = "/__mock/exports.json"
SIGN_IN_LINKS_JSON_PATH = "/__mock/sign-in-links.json"
LINK_MARK = "<link>"

SEED_CHATS = 3
SEED_FILE = ("notes.txt", b"twelve bytes\n")
"""What the runner puts in each mock's account before the tool starts: three
chats, and one file on the last of them."""


# --------------------------------------------------------------------------- #
# The two mocks
# --------------------------------------------------------------------------- #


class Client:
    """The mock's own HTTP routes, with a cookie jar and no redirect following.

    A redirect is never followed because the mock chatgpt.com's sign-in
    redirects across host names — to `chatgpt.com`, which is not where the
    mock listens — and what the seeding needs from a redirect is its
    `Location` and the cookie it set, never the page it leads to.
    """

    def __init__(self, host: str, port: int) -> None:
        self.base = f"https://{host}:{port}"
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            _NoRedirect(),
            urllib.request.HTTPSHandler(context=context),
            urllib.request.HTTPCookieProcessor(self.jar),
        )

    def request(
        self, method: str, path: str, *, data: bytes | None = None, headers: Mapping[str, str] | None = None
    ) -> tuple[int, Mapping[str, str], bytes]:
        request = urllib.request.Request(  # ruff: ignore[suspicious-url-open-usage] - the mock's own https address
            self.base + path, data=data, method=method, headers=dict(headers or {})
        )
        try:
            with self.opener.open(request, timeout=30) as answer:
                return int(answer.status), _lowered(answer.headers), answer.read()
        except urllib.error.HTTPError as answer:
            # A redirect, refused by `_NoRedirect`, arrives here with its
            # headers; the cookie processor has already read its `Set-Cookie`.
            return int(answer.code), _lowered(answer.headers), answer.read()

    def form(self, path: str, **fields: str) -> tuple[int, Mapping[str, str], bytes]:
        """Post a form, as the mock's sign-in pages take one."""
        body = urllib.parse.urlencode(fields).encode("utf-8")
        return self.request("POST", path, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})

    def post_json(self, path: str, payload: Mapping[str, Any]) -> tuple[int, Mapping[str, str], bytes]:
        """Post a JSON body, as the mock's chat routes take one."""
        body = json.dumps(payload).encode("utf-8")
        return self.request("POST", path, data=body, headers={"Content-Type": "application/json"})


def _lowered(headers: Any) -> dict[str, str]:
    """Return the headers with lowercase names: uvicorn sends `location`, and a lookup must not care."""
    return {str(key).lower(): str(value) for key, value in headers.items()}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        """Refuse every redirect: the caller reads `Location` itself."""


def sign_in_claude(client: Client, email: str, password: str) -> None:
    """Sign in to the mock claude.ai by link (`49`, brief 07 §79): the address, the link, the redeem.

    The address step mints a link where an email would go; the runner reads it
    from the listing and spends it the way the landing page's own script does —
    the token and the address posted back, with the pending-sign-in cookie the
    address step set in this jar. `password` is what every source's seeding
    takes and this one ignores: claude.ai has none.
    """
    del password
    status, headers, _ = client.form("/login/email", email=email)
    if status != 303 or "refused" in headers.get("location", ""):
        raise RuntimeError("the mock claude.ai refused the seeding address")
    minted = sign_in_links(client)
    if not minted:
        raise RuntimeError("the mock claude.ai minted no sign-in link for the seeding")
    token, address = minted[-1].split("#", 1)[1].split(":", 1)
    padded = address + "=" * (-len(address) % 4)
    email_again = base64.urlsafe_b64decode(padded).decode("utf-8")
    status, _, body = client.form("/login/redeem", token=token, email=email_again)
    if status != 200 or not json.loads(body).get("ok"):
        raise RuntimeError("the mock claude.ai refused the seeding link")


def sign_in_links(client: Client) -> list[str]:
    """Return every sign-in link the mock claude.ai has minted, oldest first."""
    _, _, body = client.request("GET", SIGN_IN_LINKS_JSON_PATH)
    return [str(item["link"]) for item in json.loads(body)]


def sign_in_chatgpt(client: Client, email: str, password: str) -> None:
    """Sign in to the mock chatgpt.com: two steps on the auth host, then its callback on the site's (`39`).

    The password step redirects to `https://chatgpt.com/auth/callback?code=…`,
    an address on a host the mock does not listen on; the code is taken off it
    and the callback asked for at the mock's own address, which is what the
    resolver rule does for Chrome.
    """
    client.form("/log-in/email", email=email)
    status, headers, _ = client.form("/log-in/password", password=password)
    location = headers.get("location", "")
    if status != 303 or "refused" in location:
        raise RuntimeError("the mock chatgpt.com refused the seeding sign-in")
    parts = urllib.parse.urlsplit(location)
    code = urllib.parse.parse_qs(parts.query).get("code", [""])[0]
    client.request("GET", f"{parts.path}?code={urllib.parse.quote(code)}")


@dataclass(frozen=True)
class Mock:
    """One site's mock, as the protocol drives it."""

    source: str
    hosts: tuple[str, ...]
    port: int
    command: str
    heading: str
    session_bound: bool
    """Whether the mock serves its link only to the signed-in session (§63)."""
    agent_signin: bool
    """Whether the tool's unattended sign-in to this site is `24`'s agent half,
    which needs `setup` to have made the Hermes profile first. Neither site's
    is, since `49`: ChatGPT's is `44`'s walk, and Claude has no unattended
    sign-in at all (brief 07 §76)."""
    link_signin: bool
    """Whether the site signs people in by link (brief 07): `login` in the
    background, the runner at the window, `login --link` — or `24`'s one
    unattended `login`."""
    files_per_upload: int
    """How many gap entries one accepted file becomes in the snapshot: the
    Claude export names a file twice (`files` and `files_v2`, `30`), ChatGPT's
    once."""
    sign_in: Callable[[Client, str, str], None]

    @property
    def display_name(self) -> str:
        return {"claude": "Claude", "chatgpt": "ChatGPT"}[self.source]


CLAUDE = Mock(
    source="claude",
    hosts=("claude.ai",),
    port=running.DEFAULT_PORT,
    command="claude-mock",
    heading="Mock claude.ai — ledger",
    session_bound=False,
    agent_signin=False,
    link_signin=True,
    files_per_upload=2,
    sign_in=sign_in_claude,
)
CHATGPT = Mock(
    source="chatgpt",
    hosts=("chatgpt.com", "auth.openai.com"),
    port=CHATGPT_PORT,
    command="chatgpt-mock",
    heading="Mock chatgpt.com — ledger",
    session_bound=True,
    agent_signin=False,
    link_signin=False,
    files_per_upload=1,
    sign_in=sign_in_chatgpt,
)
MOCKS = (CLAUDE, CHATGPT)


def seed(mock: Mock, settings: running.Settings) -> dict[str, int]:
    """Put something in the account: three chats, one file on the last of them.

    Through the mock's own routes and its own sign-in, which the mock counts
    as a sign-in of its own; the reconciliation names it.
    """
    client = Client(settings.host, settings.port)
    mock.sign_in(client, settings.email, settings.password)
    for position in range(1, SEED_CHATS + 1):
        if position == SEED_CHATS:
            name, payload = SEED_FILE
            status, _, _ = client.request(
                "POST",
                "/api/uploads",
                data=payload,
                headers={"X-File-Name": name, "Content-Type": "application/octet-stream"},
            )
            if status != 200:
                raise RuntimeError(f"the mock refused the seeding upload: HTTP {status}")
        status, _, _ = client.post_json("/api/chats", {"text": f"Seed chat {position} of {SEED_CHATS}.", "pasted": []})
        if status != 200:
            raise RuntimeError(f"the mock refused a seeding chat: HTTP {status}")
    return {"chats": SEED_CHATS, "files": 1}


def links(settings: running.Settings) -> list[str]:
    """Return every link the mock has minted, oldest first: the listing that stands in for the inbox."""
    loaded = running.witness_json(settings.host, settings.port, EXPORTS_JSON_PATH)
    return [str(item["link"]) for item in loaded]


# --------------------------------------------------------------------------- #
# The workspace, per mock
# --------------------------------------------------------------------------- #

CONFIG = """\
# Written by `rehearsal.extraction`. Every line of it is configuration an
# operator may write: the tool has no setting that names the mock (§22).

[browser]
{executable}headless = {headless}
cdp_port = {cdp_port}
extra_args = [
{extra_args}
]

[hermes]
home = {hermes_home}

[accounts]
dir = {accounts}

[store]
dir = {store}
"""


def settings_for(base: running.Settings, mock: Mock, root: Path) -> running.Settings:
    """One mock's settings: its own root, its own port, the rest the command line's."""
    return running.Settings(
        root=root / mock.source,
        mode=base.mode,
        host=base.host,
        port=mock.port,
        chrome=base.chrome,
        headless=base.headless,
        email=base.email,
        password=base.password,
        proxy_free=base.proxy_free,
        cdp_port=base.cdp_port,
    )


def prepare(settings: running.Settings, mock: Mock, *, store: Path) -> dict[str, Any]:
    """Prepare the workspace an operator would have for this mock, and check the mock is fresh."""
    counted = running.ledger(settings.host, settings.port)
    if any(counted.values()):
        raise running.NotFreshError(
            f"the {mock.command} has already counted "
            + ", ".join(f"{key}={value}" for key, value in counted.items() if value)
            + " — restart it, so that its ledger is the whole of this rehearsal"
        )
    settings.workspace.mkdir(parents=True, exist_ok=True)
    pin = running.spki_pin(settings.host, settings.port)
    arguments = running.chrome_args(settings, pin, hosts=mock.hosts)
    executable = f"executable = {json.dumps(settings.chrome)}\n" if settings.chrome else ""
    (settings.workspace / "config.toml").write_text(
        CONFIG.format(
            executable=executable,
            headless=json.dumps(settings.headless),
            cdp_port=settings.cdp_port or running.free_port(),
            extra_args="".join(f"  {json.dumps(item)},\n" for item in arguments).rstrip("\n"),
            hermes_home=json.dumps(str(settings.root / "hermes-home")),
            accounts=json.dumps(str(settings.accounts_dir)),
            store=json.dumps(str(store)),
        ),
        encoding="utf-8",
    )
    write_executable(settings.bin, repo=running.repo_root(), state=settings.bin / "profile.json")
    certificate = settings.root / f"{mock.command}.pem"
    certificate.write_text(ssl.get_server_certificate((settings.host, settings.port)), encoding="utf-8")
    return {"pin": pin, "extra_args": arguments, "certificate": certificate}


def environment(settings: running.Settings, certificate: Path) -> dict[str, str]:
    """`run.py`'s environment, plus what a browserless fetch of the mock's link needs.

    `SSL_CERT_FILE` is the mock's own certificate, written from what it served;
    `no_proxy` keeps a proxied machine from sending a loopback address through
    the proxy. Neither is a secret and both are what the mock's README tells an
    operator to set.
    """
    env = running.environment(settings)
    env["SSL_CERT_FILE"] = str(certificate)
    env["no_proxy"] = settings.host
    return env


# --------------------------------------------------------------------------- #
# The protocol
# --------------------------------------------------------------------------- #


@dataclass
class Half:
    """One mock's half of the rehearsal: what it was told, what it counted, what the tool filed."""

    mock: Mock
    settings: running.Settings
    runner: running.Runner
    extra_args: Sequence[str]
    seeded: dict[str, int]
    links: list[str]
    counted: dict[str, int]
    first_digest: tuple[str, str]
    """The first snapshot's archive and manifest, hashed after the first fetch (§39, question 6)."""
    blocks: dict[str, str]


def protocol(
    mock: Mock, settings: running.Settings, *, store: Path, extra_args: Sequence[str], env: Mapping[str, str]
) -> Half:
    """§68's protocol against one mock, in §68's order."""
    runner = running.Runner(settings=settings, env=env)
    seeded = seed(mock, settings)
    source = ("--source", mock.source, "--account", ACCOUNT)
    blocks: dict[str, str] = {}
    if mock.agent_signin:
        runner.run("setup", "setup")
    if mock.link_signin:
        running.sign_in_by_link(runner, *source)
    else:
        runner.run("login", "login", *source)
    blocks["ask"] = runner.run("extract (ask 1)", "extract", *source).stdout
    minted = links(settings)
    first = minted[-1] if minted else ""
    blocks["fetch 1"] = runner.run(
        "extract --link (fetch 1)", "extract", *source, "--link", first, secrets=(first,)
    ).stdout
    first_digest = digest_of(store / mock.source / ACCOUNT)
    runner.run("extract (ask 2)", "extract", *source)
    minted = links(settings)
    second = minted[-1] if len(minted) > 1 else ""
    blocks["fetch 2"] = runner.run(
        "extract --link (fetch 2)", "extract", *source, "--link", second, secrets=(second,)
    ).stdout
    counted = running.ledger(settings.host, settings.port)
    runner.run("session status", "session", "status", *source)
    runner.run("logout", "logout", *source)
    return Half(
        mock=mock,
        settings=settings,
        runner=runner,
        extra_args=extra_args,
        seeded=seeded,
        links=minted,
        counted=counted,
        first_digest=first_digest,
        blocks=blocks,
    )


def digest_of(account: Path) -> tuple[str, str]:
    """Return the oldest snapshot's archive and manifest hashes, or empty strings."""
    stamps = sorted(path for path in account.glob("*") if path.is_dir()) if account.exists() else []
    if not stamps:
        return "", ""
    first = stamps[0]
    return _sha256(first / "export.zip"), _sha256(first / "snapshot.json")


def _sha256(path: Path) -> str:
    """Return the file's SHA-256, or an empty string when it cannot be read."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


# --------------------------------------------------------------------------- #
# The pass criteria
# --------------------------------------------------------------------------- #


def manifests(account: Path) -> list[dict[str, Any]]:
    """Every complete snapshot's manifest under one account, oldest first."""
    found: list[dict[str, Any]] = []
    if not account.exists():
        return found
    for stamp in sorted(path for path in account.glob("*") if path.is_dir()):
        if (stamp / "COMPLETE").exists():
            manifest = running.load(stamp / "snapshot.json")
            manifest["_stamp"] = stamp.name
            found.append(manifest)
    return found


def trace_lines(root: Path, step: running.Outcome) -> list[dict[str, Any]]:
    """Return the parsed lines of the step's trace, or nothing when it left none."""
    if step.trace is None:
        return []
    parsed: list[dict[str, Any]] = []
    for line in (root / step.trace).read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            parsed.append(item)
    return parsed


def leaked(root: Path, tokens: Sequence[str]) -> list[str]:
    """Every file under `root` that carries one of the tokens. Archives are skipped: they are the vendor's bytes."""
    found: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix == ".zip":
            continue
        try:
            text = path.read_bytes()
        except OSError:
            continue
        if any(token.encode("utf-8") in text for token in tokens if token):
            found.append(str(path.relative_to(root)))
    return found


def criteria(half: Half, *, store: Path) -> list[running.Criterion]:  # ruff: ignore[too-many-locals] - one local per criterion
    """§68's checks, as numbers and verdicts, for one mock."""
    mock, settings, steps = half.mock, half.settings, half.runner.steps
    account = store / mock.source / ACCOUNT
    found = manifests(account)
    by_name = {step.name: step for step in steps}
    asks = [by_name.get("extract (ask 1)"), by_name.get("extract (ask 2)")]
    fetches = [by_name.get("extract --link (fetch 1)"), by_name.get("extract --link (fetch 2)")]
    heading = f"{mock.display_name} extraction — {ACCOUNT}"
    asked = all(step is not None and step.ok and step.stdout.startswith(heading) for step in asks)
    fetched = all(step is not None and step.ok and step.stdout.startswith(heading) for step in fetches)
    conversations = [int(item.get("counts", {}).get("conversations", -1)) for item in found]
    gaps = [sum(int(gap.get("count", 0)) for gap in item.get("gaps", [])) for item in found]
    files = [item.get("counts", {}).get("files") for item in found]
    expected_gap = half.counted.get("files_accepted", 0) * mock.files_per_upload
    stamps = [item["_stamp"] for item in found]
    tokens = [urllib.parse.urlsplit(link).path.rsplit("/", 1)[-1].removesuffix(".zip") for link in half.links]
    leaks = leaked(settings.root, tokens) + leaked(store / mock.source, tokens)
    driving = (
        (["login", "login --link"] if mock.link_signin else ["login"])
        + ["extract (ask 1)", "extract (ask 2)"]
        + (["extract --link (fetch 1)", "extract --link (fetch 2)"] if mock.session_bound else [])
    )
    traced = {step.name: step.traces for step in steps}
    headers = [trace_lines(settings.root, step)[0] if step.trace else {} for step in steps]
    named = all(
        header.get("source") == mock.source and header.get("host") == mock.hosts[0] for header in headers if header
    )
    password_steps = sum(
        1 for step in steps for line in trace_lines(settings.root, step) if line.get("helper") == "password-step"
    )
    login = by_name.get("login")
    spent = by_name.get("login --link")
    login_lines = trace_lines(settings.root, login) if login else []
    # What the tool did that the mock counts as a sign-in: a password typed
    # (ChatGPT's walk), or a link spent (Claude's two commands).
    tool_sign_ins = (1 if spent is not None and spent.ok else 0) if mock.link_signin else password_steps
    signed_in = bool(login and login.ok) and (not mock.link_signin or bool(spent and spent.ok))
    checks = [
        running.Criterion(
            "login signs the source account in",
            signed_in,
            (f"exit {login.exit_code}" if login else "not run")
            + (
                f", login --link exit {spent.exit_code}"
                if spent
                else (", login --link not run" if mock.link_signin else "")
            ),
        ),
        running.Criterion(
            "both asks are taken and print the block", asked, f"{sum(1 for s in asks if s and s.ok)}/2 asks"
        ),
        running.Criterion(
            "the mock minted one link per ask",
            len(half.links) == 2 and half.counted.get("exports_requested", 0) == 2,
            f"{len(half.links)} links listed, exports requested: {half.counted.get('exports_requested', 0)}",
        ),
        running.Criterion(
            "both fetches file a complete snapshot",
            fetched and len(found) == 2,
            f"{sum(1 for s in fetches if s and s.ok)}/2 fetches, {len(found)} complete snapshots",
        ),
        running.Criterion(
            "the second stamp sorts after the first",
            len(stamps) == 2 and stamps[0] < stamps[1],
            " < ".join(stamps) if stamps else "no snapshots",
        ),
        running.Criterion(
            "ledger: conversations == chats created",
            bool(found) and all(count == half.counted.get("chats_created", 0) for count in conversations),
            f"{conversations} == {half.counted.get('chats_created', 0)} (seeded {half.seeded['chats']})",
        ),
        running.Criterion(
            "ledger: the gap is the files the mock accepted, none of them carried",
            bool(found) and all(gap == expected_gap for gap in gaps) and all(item in {None, 0} for item in files),
            f"gaps {gaps} == {half.counted.get('files_accepted', 0)} × {mock.files_per_upload}, files carried {files}",
        ),
        running.Criterion(
            "the first snapshot is unchanged by the second",
            bool(found) and half.first_digest == digest_of(account),
            "archive and manifest hashes equal" if half.first_digest == digest_of(account) else "changed",
        ),
        running.Criterion(
            "snapshots lists both rows",
            "snapshots" in by_name
            and by_name["snapshots"].ok
            and by_name["snapshots"].stdout.count(f"{mock.source}/{ACCOUNT}") == 2,
            f"{by_name['snapshots'].stdout.count(f'{mock.source}/{ACCOUNT}') if 'snapshots' in by_name else 0} rows",
        ),
        running.Criterion(
            "the link is in no file the run left",
            not leaks,
            "none" if not leaks else ", ".join(leaks[:3]),
        ),
        running.Criterion(
            "one trace per step that drove a tab, each naming the source",
            all(traced.get(name) == 1 for name in driving) and named,
            f"{[traced.get(name, 0) for name in driving]} for {len(driving)} steps",
        ),
        running.Criterion(
            "ledger: sign-ins == the seeding's + the tool's",
            half.counted.get("sign_ins", 0) == 1 + tool_sign_ins,
            f"{half.counted.get('sign_ins', 0)} == 1 + {tool_sign_ins}"
            + (" (a link spent)" if mock.link_signin else " (password steps)"),
        ),
    ]
    if mock.link_signin:
        saw_it = bool(login and running.LINK_SENT_LINE in login.stdout)
        checks += [
            running.Criterion(
                "login saw the link sent and said so",
                saw_it,
                "the line is in its stdout" if saw_it else "the line is not in its stdout",
            ),
            running.Criterion(
                "ledger: sign-in links minted == the seeding's + the tool's",
                half.counted.get("links_minted", 0) == 2,
                f"{half.counted.get('links_minted', 0)} == 1 + 1",
            ),
        ]
    if mock.session_bound:
        crossed = any(line.get("host") == mock.hosts[1] for line in login_lines)
        certified = sorted({str(line.get("host")) for line in login_lines if line.get("what") == "certificate"})
        checks.append(
            running.Criterion(
                "the sign-in crossed to the auth host and both hosts were certified",
                crossed and certified == sorted(mock.hosts),
                f"crossed: {crossed}, certified: {certified}",
            )
        )
    return checks


# --------------------------------------------------------------------------- #
# The record
# --------------------------------------------------------------------------- #

RECORD = """\
# Rehearsal {number:02d} — extraction

**Kind:** Rehearsal record — what a rehearsal measured, not what was designed.
Produced by [`46`](../specs/impl/46-extraction-rehearsal.md).
**Answers:** [§68](../specs/06-chatgpt-extraction.md)'s protocol against both mocks,
with numbers, and [§39](../specs/03-extraction-and-backup.md)'s questions 3 and 6 where
a mock can answer them.
**Rehearsal run:** {date}. **Mode:** `{mode}`.
**Tool:** {tool}. **Scripted agent:** {agent}. **Chrome:** {chrome}.
**Mock claude.ai:** {claude_mock}. **Mock chatgpt.com:** {chatgpt_mock}.

An extraction rehearsal is §68's protocol run by the shipped tool against each
site's mock: the account seeded through the mock's own routes, then `login`, an
ask, the link read from the listing that stands in for the inbox, the fetch, a
second ask and a second fetch, `snapshots`, `session status`, `logout`.
It is **not evidence about either site**: every `*unknown*` and `*reported*` row
of [`claude-ui-map.md`](claude-ui-map.md) and
[`chatgpt-ui-map.md`](chatgpt-ui-map.md) is what it was after it (§56). The
mock claude.ai's link is fetched without a browser, the mock chatgpt.com's
through the session (§63).

Nothing here carries conversation content or a link: the link is a credential
to the archive while it lives, and every place the runner wrote one it wrote
`<link>` (§66).

{halves}
**Verdict:** {verdict}. {mark}

## What it found

{findings}

## What it could not exercise

{gaps}
"""

HALF = """\
## The {title}

| | |
| --- | --- |
| Seeded | {chats} chats, {files} file |
| Chrome extra arguments | {extra_args} |

### The protocol

| Step | Exit | Seconds | Note |
| --- | --- | --- | --- |
{protocol}

### The traces

| Step | Trace | Lines | Certificate | Agent |
| --- | --- | --- | --- | --- |
{traces}

### The blocks, and the ledger beside them

```text
{ask_block}
```

```text
{fetch_1}
```

```text
{fetch_2}
```

```text
{ledger_block}
```

### Pass criteria

| Criterion | Number | Verdict | Mark |
| --- | --- | --- | --- |
{criteria}

"""

CANNOT_EXERCISE = """\
- Anything about claude.ai or chatgpt.com. A mock is a consequence of its UI
  map, never evidence about it (§56).
- An email: the mock lists its links where the inbox would be, and the runner
  reads the listing where a person would read a message.
- The 24-hour expiry of a link, an export already requested and still
  processing, a rate limit on asking: the mocks have no clock (§58).
- The auth host's real screens and the real Data controls path: the walk and
  the path are the mock's, and the first real run is what corrects them (§69).
- Whether the real ChatGPT link needs the session at all: the mock mirrors the
  documentation, and only a real link answers (§69).
"""

STANDING_FINDINGS = (
    (
        "The seeding signs in to the mock through its own routes before the tool "
        "starts, and the mock counts that sign-in; the reconciliation of sign-ins "
        "reads `1 + the tool's` — a password typed on the mock chatgpt.com, a link "
        "spent on the mock claude.ai — rather than subtracting it silently."
    ),
    (
        "The mock claude.ai's sign-in is brief 07's two commands: `login` runs in "
        "the background, the runner enters the address at its window as a person "
        "would, and `login --link` spends the link the mock minted where an email "
        "would go. Both steps leave a trace, told apart by the header's `flags`."
    ),
    (
        "A file the mock claude.ai accepted is two gaps in the snapshot, because the "
        "Claude export names a file under both `files` and `files_v2` and `30` counts "
        "every reference; the mock chatgpt.com's is one. Neither carries bytes, which "
        "is the mocks' gap and not the exports'."
    ),
    (
        "The mock claude.ai's link is fetched with the mock's certificate trusted "
        "through `SSL_CERT_FILE`, written by the runner from the certificate the mock "
        "served; the mock chatgpt.com's is fetched through the session, and the tool "
        "is told to trust nothing."
    ),
)


def ledger_block(mock: Mock, counted: Mapping[str, int]) -> str:
    """Return the mock's seven-row block, rebuilt from its numbers under its own heading."""
    labels = (
        ("sign_ins", "Sign-ins:"),
        ("chats_created", "Chats created:"),
        ("messages_received", "Messages received:"),
        ("files_accepted", "Files accepted:"),
        ("renames", "Renames:"),
        ("exports_requested", "Exports requested:"),
        ("links_minted", "Sign-in links minted:"),
    )
    lines = [mock.heading, ""]
    for key, label in labels:
        lines.append(f"{label}{counted.get(key, 0):>{32 - len(label)}}")
    return "\n".join(lines)


def render_half(half: Half, checks: Sequence[running.Criterion], mark: str) -> str:
    """Render one mock's half of the record."""
    steps = half.runner.steps
    return HALF.format(
        title=f"mock {half.mock.hosts[0]}",
        chats=half.seeded["chats"],
        files=half.seeded["files"],
        extra_args=", ".join(f"`{item}`" for item in half.extra_args),
        protocol="\n".join(
            f"| `{step.name}` | {step.exit_code} | {step.seconds:g} | {step.note or ''} |" for step in steps
        ),
        traces="\n".join(running.trace_row(half.settings.root, step) for step in steps),
        ask_block=half.blocks.get("ask", "").strip("\n"),
        fetch_1=half.blocks.get("fetch 1", "").strip("\n"),
        fetch_2=half.blocks.get("fetch 2", "").strip("\n"),
        ledger_block=ledger_block(half.mock, half.counted),
        criteria="\n".join(f"| {item.name} | {item.detail} | {item.verdict} | {mark} |" for item in checks),
    )


def render(
    halves: Sequence[tuple[Half, Sequence[running.Criterion]]],
    *,
    number: int,
    date: str,
    mode: str,
    versions: Mapping[str, str],
    findings: Sequence[str],
) -> str:
    mark = running.MARK.format(date=date)
    passed = all(item.passed for _, checks in halves for item in checks)
    return RECORD.format(
        number=number,
        date=date,
        mode=mode,
        tool=versions.get("tool", "unknown"),
        agent=versions.get("agent", "unknown"),
        chrome=versions.get("chrome", "unknown"),
        claude_mock=versions.get("claude-mock", "unknown"),
        chatgpt_mock=versions.get("chatgpt-mock", "unknown"),
        halves="".join(render_half(half, checks, mark) for half, checks in halves),
        verdict="passed" if passed else "not passed",
        mark=mark,
        findings="\n".join(f"- {item}" for item in findings) or "- Nothing new.",
        gaps=CANNOT_EXERCISE,
    )


def findings_of(halves: Sequence[tuple[Half, Sequence[running.Criterion]]]) -> list[str]:
    """Return what this run has to say, in one line each, and the standing findings after."""
    found: list[str] = []
    for half, checks in halves:
        name = half.mock.hosts[0]
        found += [
            f"{name}: `{step.name}` exited {step.exit_code}." + (f" {step.note}" if step.note else "")
            for step in half.runner.steps
            if not step.ok and not step.deliberate
        ]
        found += [f"{name}: {item.name}: {item.detail}." for item in checks if not item.passed]
        found += [
            f"{name}: two traces for one step: `{step.name}` left {step.traces}."
            for step in half.runner.steps
            if step.traces > 1
        ]
    return [*found, *STANDING_FINDINGS]


def versions_of(
    base: running.Settings, env: Mapping[str, str], halves: Sequence[tuple[Half, Sequence[running.Criterion]]] = ()
) -> dict[str, str]:
    """Return the versions a record names, each read rather than assumed.

    Chrome's is read off a trace header the tool wrote (`33`), which names the
    browser it actually drove, rather than asked of a binary by a name this
    machine may not have.
    """
    versions = running.versions_of(base, env)
    versions["claude-mock"] = versions.pop("mock")
    for half, _ in halves:
        for step in half.runner.steps:
            lines = trace_lines(half.settings.root, step)
            if lines and lines[0].get("chrome"):
                versions["chrome"] = str(lines[0]["chrome"])
                break
    versions["chatgpt-mock"] = running.captured(
        [running.shutil.which("chatgpt-mock") or "chatgpt-mock", "--version"], env
    )
    return versions


# --------------------------------------------------------------------------- #
# The command
# --------------------------------------------------------------------------- #


def main(base: running.Settings, *, chatgpt_port: int, record: Path | None, number: int) -> int:
    """Run §68's protocol against both mocks, print the criteria, leave the record."""
    store = base.root / "store"
    halves: list[tuple[Half, Sequence[running.Criterion]]] = []
    print(f"rehearsal: extraction, against the mocks on {base.host}:{base.port} and {base.host}:{chatgpt_port}")
    mocks = (CLAUDE, replace(CHATGPT, port=chatgpt_port))
    prepared: list[tuple[Mock, running.Settings, dict[str, Any]]] = []
    for mock in mocks:
        settings = settings_for(base, mock, base.root)
        prepared.append((mock, settings, prepare(settings, mock, store=store)))
    for mock, settings, made in prepared:
        print(f"\n  against the mock {mock.hosts[0]}")
        env = environment(settings, made["certificate"])
        half = protocol(mock, settings, store=store, extra_args=made["extra_args"], env=env)
        # `snapshots` once both halves have filed, so the listing shows both rows.
        halves.append((half, []))
    for half, _ in halves:
        half.runner.run("snapshots", "snapshots")
    halves = [(half, criteria(half, store=store)) for half, _ in halves]

    print()
    for half, checks in halves:
        print(f"  {half.mock.hosts[0]}")
        for item in checks:
            print(f"  {item.verdict:<4} {item.name}  ({item.detail})")
    passed = all(item.passed for _, checks in halves for item in checks)
    print(f"\nrehearsal: {'passed' if passed else 'NOT PASSED'}")

    if record is not None:
        date = datetime.now(UTC).date().isoformat()
        text = render(
            halves,
            number=number,
            date=date,
            mode=base.mode,
            versions=versions_of(base, environment(prepared[0][1], prepared[0][2]["certificate"]), halves),
            findings=findings_of(halves),
        )
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(text, encoding="utf-8")
        print(f"record: {record}")
    return 0 if passed else 1
