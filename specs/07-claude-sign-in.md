# Claude sign-in by link

**Brief 07.** Section numbers continue from [`06-chatgpt-extraction.md`](06-chatgpt-extraction.md),
which ends at §71, so that `§N` names exactly one section anywhere in this repository. The
words used here are defined in [`CONTEXT.md`](../CONTEXT.md).

## 72. Goal

Give the tool a **Claude sign-in that works**. claude.ai has no password sign-in: a person
enters an address, the vendor emails a link, and redeeming that link is what signs them in.
Everything the tool does with a Claude account today assumes otherwise — `24`'s unattended
run types an email and a password into a form, and
[`docs/LIMITATIONS.md`](../docs/LIMITATIONS.md) states *password sign-in only* as a
limitation by construction. That path cannot succeed, on the source side or the destination
side, and this brief replaces it.

It replaces it with two commands and a browser:

```text
Claude account
      │
      │ login: a window opens at the sign-in page
      ▼
   the person enters the address, and clears whatever is asked of them
      │
      │ an email ──── a link ──── login --link: spent in the same profile
      ▼
   extract: the export ask ───► an email ───► extract --link ───► Snapshot

```

The sign-in is **in the browser, and it has to be**
([ADR 0008](../docs/adr/0008-the-sign-in-stays-in-the-browser.md)). A command-line tool
making those calls itself was designed and withdrawn: `send_magic_link` carries an hCaptcha
attestation and needs a cleared Cloudflare cookie beside it, and the tool produces neither.
Brief 06 §63 therefore stands unamended — the session's cookie never leaves the browser,
and the tool never learns what it is.

Nothing about the store, the snapshot or the archive changes. A Claude snapshot is what it
was, filed where it was, by the command that filed it.

## 73. The two commands

```bash
dataporter login --source claude --account work
dataporter login --source claude --account work --link <url>

```

The first opens a window at Claude's sign-in page, prints the block below, and **keeps the
window open until the link has been spent in it**. It waits in two phases on one number,
`timeouts.login_s`: one for the address and whatever Claude asks of the person, and — restarted
the moment the page says the link is on its way — one for the link to arrive and be spent. It
ends signed in, with the second block, or timed out with exit `3`.

```text
Claude sign-in — work

A window is open at Claude's sign-in page. Enter the account's address
there, and clear anything Claude asks of you.

Claude will email a sign-in link. The link signs in once and expires, and
it must be spent here rather than opened. When it arrives:

  dataporter login --source claude --account work --link <url>

```

When Claude says the link is on its way — a page the tool recognises by its controls and
never by its words, so it reads the same in any language — one more line, and the clock
restarts:

```text
The link is on its way. This window stays open for 10 minutes; spend the link before it closes.

```

The second command, run from another terminal while that window is open, spends the link in
it: the same profile on the same debug port, adopted rather than launched, and the tab the
person used pointed at the link. The first command sees the account signed in, closes the
window, and both commands print the same ending, so that each terminal is complete on its
own:

```text
Signed in to Claude — work
Session stored in ~/.dataporter/accounts/claude/work/browser-profile/.

```

The window stays open rather than closing when the link is sent, because whether the pending
sign-in survives Chrome closing is unobserved (ADR 0008). With no window open — the first
command timed out, or the link arrived the next day — the second launches the profile and
tries anyway. That works exactly when the pending sign-in survived; when it did not, the tool
says so rather than guessing.

Both blocks and the line are golden (`specs/README.md`), as brief 03's and brief 06's are. Two
sentences earn their place. *Clear anything Claude asks of you* is the attestation of §78,
named without naming a mechanism that will change. *Spent here rather than opened* is the
trap: the link is single-use, and a person who opens it in their mail client is shown a code
rather than signed in. Whether that spends the link is unobserved; what is certain is that
the tool has no window open for the code to be typed into (§80).

A link that is refused or expired stops with exit `3` and names the first command as the
remedy; a link that lands the tab back on a code prompt — the pending sign-in is not in this
profile — says that instead, with the same remedy.

There is no `--email` flag and no sign-in ask on the tool's side. The address is typed into
the vendor's page by the person whose address it is, which is also why nothing here ever
holds one. Neither command has an unattended half: `--non-interactive login`, with or
without `--link`, exits `2` and names the command a person runs instead (§76).

## 74. What the tool never sees

The sign-in link is a credential while it lives, and is handled as the export link is
(§66): validated as `https` before anything is driven to it, never written to the store,
never kept after it is spent, and never logged — it joins the run log's forbidden fields,
and `46`'s guard already strips a query from every URL a trace records, which is what keeps
a link out of one.

What the tool holds afterwards is what it has always held: a browser profile.
No credential, no token, no expiry — §63's rule, unchanged, and `session logout` still
deletes a profile and says, truthfully, that the deletion is local and the account is
untouched.

## 75. The destination account

Nothing new. The destination is a Claude account, its session is the profile `07` opens,
and a person has always signed it in through that window — with a link now, as everywhere
else. What it loses is the same thing the source loses: `24`'s unattended password path,
which never worked here either.

## 76. What a cron job loses

There is no unattended Claude sign-in any more, and there will not be one — not the first
command, and not the second either, which spends a link a person read. Signing in needs
a person to read an email, and may need one to clear a challenge. `docs/LIMITATIONS.md`
promises that nothing in the tool reads a mailbox or solves a challenge; both halves of
that promise are kept here, and the second is now load-bearing rather than incidental.

A backup whose Claude session has expired stops and names `login` as the remedy, which is
§12's answer for a step only a person can take. `24`'s agent sign-in stays in the tree for
a source that can still use it; Claude is marked as having none.

## 77. The export page's real address

Claude's export is asked for from the account's data controls, which claude.ai serves at a
fragment of its app rather than a path of its own:
`https://claude.ai/new#settings/data-privacy-controls` (*reported*, 2026-09-14). `31`'s
placeholder path was a guess and is wrong.

A fragment is not a path. It is not something a surface can admit or a trace can record —
`46`'s guard strips it, so a trace of the ask shows `https://claude.ai/new` — and a source
holds one address for where its export is asked for, fragment included, rather than a path
the tool then has to reassemble.

## 78. What a vendor can make a person's step

`send_magic_link` requires an attestation (`CONTEXT.md`): a token the vendor's own page
computes, and a cookie that exists because a challenge was cleared. The tool cannot make
either, and will not learn to.

The rule this brief sets, which is not about Claude: **a step behind an attestation is a
step the tool hands to a person.** Not retried, not worked around, not automated with a
better disguise. The window opens, the person clears it, and the run continues or stops
with `login` as the remedy. A tool that got good at clearing bot management would be a tool
whose runs a vendor cannot tell from an attack, and that is a worse thing to be than
manual.

This is also why §61's deterministic walk is not extended to Claude. A walk that fills a
form is fine where the form is all there is; where an attestation sits in front of it, the
walk ends at a wall and the honest move is to have opened a window in the first place.

## 79. The mock

The mock claude.ai grows the sign-in by link: an address submitted, a link minted rather
than mailed — the shape `32` already established for the export link — and a redemption
that signs the browser in. So the flow is rehearsed without an account, as every flow
before it was.

The mock has no attestation to imitate, deliberately. It is what the tool is pointed at
when nobody is proving anything to anyone, and a rehearsal that cleared a fake challenge
would prove only that the fake could be cleared.

## 80. Later

Deliberately left, and unclaimed until one of them is built:

- **Gemini**, whose sign-in nobody has looked at, and which may be a third shape again.
- **`--code`.** The page that says the link is on its way also takes a code: the digits
  Claude shows when the link is opened where the pending sign-in is not. A second way to
  spend a link, typed through CDP as `24` typed a password and never through the agent;
  wanted, and waiting on an observation of the code page that nobody has made.
- **Whether the pending sign-in survives the window closing.** §73 keeps the window open
  so as not to depend on it; the branch that launches a profile for a link would stop being
  a hope the day somebody reads the cookie's lifetime off the page.
- **Whether the export ask needs the browser.** It is a request made from a signed-in
  session and may carry no attestation; nobody has captured it. It is asked for by a click
  today (§31) and that keeps working, so this is an optimisation, not a gap.
- **Telling a person their session is about to expire.** Wanted, and not available: the tool
  holds no credential and therefore no expiry, and asking the vendor would be a request of
  its own. What it can still do is fail with `login` as the remedy, which it does.
- **Revoking a session from the tool.** `session logout` is local by construction (§74).
