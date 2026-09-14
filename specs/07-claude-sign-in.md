# Claude sign-in by link

**Brief 07.** Section numbers continue from [`06-chatgpt-extraction.md`](06-chatgpt-extraction.md),
which ends at §71, so that `§N` names exactly one section anywhere in this repository. The
words used here are defined in [`CONTEXT.md`](../CONTEXT.md).

## 72. Goal

Give the tool a **Claude sign-in that works**. claude.ai has no password sign-in: a person
enters an address, the vendor emails a sign-in link, and redeeming that link is what signs
them in. Everything the tool does with a Claude account today assumes otherwise — `24`'s
unattended run types an email and a password into a form, and
[`docs/LIMITATIONS.md`](../docs/LIMITATIONS.md) states *password sign-in only* as a
limitation by construction. That path cannot succeed, on the source side or the
destination side, and this brief replaces it.

It replaces it with the shape brief 03 already built for the export and brief 06 already
proved: an ask, an email, a link a person hands back.

```text
Claude account
      │
      │ login: the sign-in ask                ─┐
      ▼                                        │ the source session:
   an email ──── the person ──── a link        │ a credential, not a profile
      │                                        │ ([ADR 0008](../docs/adr/0008-claude-is-an-api-source.md))
      │ login --link: signed in, and kept     ─┘
      ▼
   extract: the export ask ───► an email ───► extract --link ───► Snapshot

```

Claude becomes an **API source** (ADR 0008): the tool asks it directly and holds the
credential the vendor issues, rather than driving a browser and never learning its cookie
as §63 requires of a source driven in one. §63 is unchanged for ChatGPT and for Gemini
when it lands; this brief is the exception, and ADR 0008 is where the exception is
recorded.

Nothing about the store, the snapshot or the archive changes. A Claude snapshot is what it
was, filed where it was, by the command that filed it.

## 73. The sign-in ask and the sign-in link

Two commands, in `extract`'s shape (§31, §60) — an ask, then the same verb with the link
the vendor sent:

```bash
dataporter login --source claude --account work --email me@example.com
dataporter login --source claude --account work --link <url>

```

```text
Claude sign-in — work

Link requested 2026-09-30 18:12 UTC.
Claude will email a sign-in link to me@example.com.
The link signs in once and expires. Do not open it in a browser. When it arrives:

  dataporter login --source claude --account work --link <url>

```

```text
Signed in to Claude — work
Session expires 2026-10-30 18:12 UTC.

```

Both blocks are golden (`specs/README.md`), as brief 03's and brief 06's are. The third
line of the first block is the one that earns its place: the link is single-use, so a
person who opens it in a mail client has spent it, and the remedy — asking again — is the
next thing the block would otherwise have to explain.

The address is given once. `--email` is required on the first sign-in for an account and
remembered in the account home; afterwards the account's label is the whole of what a
person types. The destination account, which has no label, falls back to
`DATAPORTER_AUTH__EMAIL` as `24` left it.

A second sign-in ask **supersedes** the first rather than being refused. This is where the
sign-in ask parts company with the export ask, which §31 refuses while one is open and
makes a person say `--abandon`: an export ask is expensive and rate-limited at the vendor,
and *the mail never arrived, send another* is the ordinary course of a sign-in rather than
a mistake to be guarded against. A link that is refused or expired stops with exit `3` and
names the ask as the remedy; the record survives, so asking again is one command.

## 74. What the tool holds, and what never sees it

The credential the vendor issues is the source session (`CONTEXT.md`). It lives in the
account home at `0600`, beside the open ask and never in the store, and it is written the
way `31` writes an ask: created exclusively, and only once the vendor has answered.

It is a credential in §32's sense, so it is handled as the link is (§66). It joins the run
log's forbidden fields; it reaches no log line, no action log and no trace; it is never
printed, never passed to a helper, and never present in the environment the agent is built
with. What a trace of a sign-in carries is what a trace has always carried: hosts, and
never paths, queries or fragments — `46`'s guard already strips a query from every URL it
records, which is what keeps a sign-in link out of one.

`session logout` deletes the credential **and** the browser profile. Deleting one and not
the other would sign a person back in on their next command, and *I logged out and it came
back* is not a thing this tool does. Its promise is unchanged and still literally true: the
deletion is local, the account is untouched, and a session on another machine is not ended
by it.

## 75. The destination account

The destination account is a Claude account, so it signs in by link too, with the same
command and the same words. It differs in one thing: Hermes drives claude.ai in a browser
to perform the migration, and a credential in a file signs no browser in. So for the
destination the tool **plants** the cookie into its profile over CDP — at the moment the
link is redeemed, and again on demand before a run that needs the profile signed in, so a
wiped or expired profile costs no second email.

This is the half of ADR 0008 that was considered and taken here rather than for the source:
the tool sees the cookie, hands it to Chrome, and keeps it only where §74 says it is kept.

## 76. What a cron job loses

There is no unattended Claude sign-in any more, and there will not be one: signing in
requires reading an email, and [`docs/LIMITATIONS.md`](../docs/LIMITATIONS.md) promises
that nothing in the tool reads a mailbox and nothing will. That promise is kept here —
the person hands the link over, exactly as they hand over an export link.

So a backup whose Claude session has expired stops and names `login` as the remedy, which
is §12's answer for a step only a person can take. To keep that from being discovered by a
backup at three in the morning, `session status` reports the session's remaining lifetime
and warns while there is still time to act. `24`'s unattended sign-in stays in the tree for
a source that can still use it; Claude is marked as having none.

## 77. The export ask, without a page

An API source has no export page (`CONTEXT.md`): the ask is a request rather than a click,
so `extract --source claude --account work` stops opening a browser. The ask block, the
open ask, the link, the fetch, the snapshot and the store are unchanged — §31's shape
holds, and what changes underneath it is how the ask is made.

Claude's export is asked for from the account's data controls, which claude.ai serves at a
fragment of its app rather than a path of its own
(`https://claude.ai/new#settings/data-privacy-controls`, *reported*, 2026-09-14). A
fragment is not a path: it is not something a surface can admit or a trace can record, and
this is the second reason the ask is a request rather than a walk to a page.

## 78. The shapes, and the guard

Three requests are the whole of what the tool asks of claude.ai: send the link, redeem the
link, ask for the export. Each is pinned byte-exact in the slice that builds it — method,
address, the headers that matter, the body, and what comes back — and each is marked in
the discipline this repository uses for a claim about a real site: *observed on a date*,
*reported*, or *unknown*. **All three are `*unknown*` as this brief is written.** No one
has watched claude.ai make them, and the slices from `49` on are blocked until someone has.

Every call is guarded the way §61 guards a sign-in walk: a response that is not the shape
expected stops the run with exit `3` and the `login` instruction, rather than being
interpreted generously. A vendor's private interface changes without notice, and a tool
that guesses at a changed shape is a tool that writes a snapshot nobody can trust.

The window sign-in `07` built — the tool opens Chrome, the person signs in themselves —
stays, behind a flag, and is what a person reaches for the day a guard trips, a challenge
appears, or an account signs in through Google. `docs/LIMITATIONS.md` already names
`login` by hand as that remedy.

## 79. Reaching the mock without a door

The mock claude.ai grows the three requests of §78, so this flow is rehearsed without an
account as every flow before it was, and its sign-in link is minted rather than mailed —
the shape `32` already established for the export link.

A browserless client cannot be pointed at the mock the way a browser is.
[ADR 0001](../docs/adr/0001-no-door-in-the-wall.md) forbids the obvious answer: the tool
takes no host setting, so that shipped code can never distinguish a rehearsal from a real
run. The redemption stays **outside the program** — the rehearsal resolves the host and
trusts the mock's certificate at the level of the process it launches, the way
`--host-resolver-rules` lives in Chrome's launch flags rather than in the code. The
shipped client keeps one hardcoded address and one behaviour, and ADR 0001 stands
unamended.

## 80. Later

Deliberately left, and unclaimed until one of them is built:

- **Gemini**, whose sign-in shape nobody has looked at, and which may be a third kind
  beside a browser source and an API source.
- **A ChatGPT session that outlives its cookie.** §63's rule costs ChatGPT the thing this
  brief gives Claude — a session a person can re-establish from a terminal — and whether
  that is worth revisiting is a question, not a plan.
- **Revoking a session from the tool.** `session logout` is local by construction (§74); an
  API source could end the session at the vendor, which is a different promise and needs
  one.
- **The window sign-in for a source account.** §78 keeps it for the destination's sake; a
  source account reaches it only by signing in to the destination's profile, which is not
  the same thing.
