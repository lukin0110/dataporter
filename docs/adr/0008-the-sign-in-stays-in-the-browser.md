# The sign-in stays in the browser

claude.ai has no password sign-in. A person enters an address, the vendor emails a link,
and redeeming that link is what signs them in. The obvious shape for a command-line tool is
to make those two calls itself — ask for the link, then spend it — and hold whatever the
vendor hands back. We designed that, and then looked at the requests.

`POST /api/auth/send_magic_link` carries a `client_attestation` object holding an hCaptcha
token, and succeeds only alongside a `cf_clearance` cookie. Both are produced by a real
browser clearing bot management. Nothing this tool builds can produce either, and producing
them is not something it will ever try: `docs/LIMITATIONS.md` already promises that nothing
here reads a mailbox or solves a challenge.

So **Claude's sign-in happens in the browser the tool already launches**, and the tool's
part is to open the window and to spend the link in the same profile:

```bash
dataporter login --source claude --account work            # opens the sign-in page
#   the person types their address there and clears whatever is asked of them
dataporter login --source claude --account work --link <url>
```

The second step works *because* the first used the same profile: the half-finished sign-in
is already in that cookie jar, and navigating to the link completes it where it started.
Brief `06` §63 stands unamended for Claude as for ChatGPT — the session's cookie never
leaves the browser, and the tool never learns what it is.

## Considered

- **Claude as an API source**: the tool asks claude.ai directly and holds the credential the
  vendor issues. This was decided, written down, and withdrawn four days later when the
  attestation token turned up in the first captured request. Recorded here rather than
  quietly deleted, because the appeal of it survives the refutation — everything the tool
  wants from Claude *is* one request, right up until one of them requires being a browser.
- **Lifting the session cookie out of the profile** so the rest could be browserless. It
  fails the same way for the same reason: getting the cookie in the first place needs the
  browser, and §63 rejects the lifting on its own merits.
- **Solving the challenge**, by any means. Refused, and the refusal is the point rather than
  a limitation to route around: a tool that clears bot management is a tool whose runs a
  vendor cannot tell from an attack.

## Consequences

- There is no unattended Claude sign-in, and there will not be one. A backup whose session
  has expired stops and names `login` as the remedy, because a person must read an email
  and may have to clear a challenge. `24`'s unattended password path is deleted for Claude.
- The destination account needs nothing new: it is a Claude account, its session is a
  browser profile, and a person has always signed it in through the window `07` opens.
- Nothing is stored that was not stored before. No credential, no expiry, no planting; a
  source session is a browser profile, as `CONTEXT.md` has always said.
- The mock claude.ai grows the sign-in by link, so the flow is rehearsed without an account.
  It has no attestation to imitate: the mock is what the tool is pointed at when nobody is
  proving anything to anyone.
- **A vendor can make any step a person's step.** The lesson is not about Claude: any site
  may put attestation in front of any call, and the tool's answer is to hand that step to
  the person rather than to get better at pretending. `docs/LIMITATIONS.md` says so now.
