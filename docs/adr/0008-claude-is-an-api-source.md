# Claude is an API source

claude.ai has no password sign-in. A person enters an address, the vendor emails a
sign-in link, and redeeming that link is what signs them in. Brief `06` §63 settled the
opposite shape for ChatGPT: the session's cookie never leaves the browser, the tool does
not carry a cookie into a request of its own, and it never learns what the cookie is. A
link a person pastes into a terminal cannot be redeemed under that rule without opening a
browser to redeem it in.

We decided that **Claude is an API source**: the tool asks it directly, over the vendor's
own interface, and holds the credential the vendor issues. Everything the tool wants from
Claude — a link sent, a link redeemed, an export asked for — is one request, and driving a
browser to make three requests is machinery standing in the way of a command a person runs
in a terminal. §63's rule is unchanged for every source driven in a browser, which is
ChatGPT today and Gemini next; this is the exception, and this is where it is written down.

## Considered

- **Redeem the link in Chrome.** Relaunch the account's profile on the pasted address and
  let the vendor set its own cookie, so the tool never sees one and no rule moves. Rejected:
  it keeps a browser in a flow whose only other need of one is the export click, and that
  click is a request too.
- **Redeem directly, then plant the cookie into the profile.** The tool sees the cookie for
  an instant, hands it to Chrome over CDP and forgets it, leaving everything downstream
  browser-shaped. Rejected for the source, and taken for the destination, which needs a
  browser session because Hermes drives claude.ai in one.

## Consequences

- The tool holds a Claude credential. It lives in the account home at `0600`, beside the
  open ask and never in the store; it joins the run log's forbidden fields beside the link,
  and it reaches no trace, no log line and no agent environment.
- The destination account is a Claude account, so it signs in the same way, and its cookie
  is planted into its browser profile because the migration is driven in a browser. The two
  sign-ins share one command and one vocabulary; they do not share a session artifact.
- There is no unattended Claude sign-in any more. A person must read an email, so a cron
  job whose session has expired stops and names `login` as the remedy, and `session status`
  reports the remaining lifetime so that this is not first discovered by a backup at night.
- [ADR 0001](0001-no-door-in-the-wall.md) stands. The shipped client carries one hardcoded
  address and takes no host setting; a rehearsal redirects it from outside the program, the
  way `--host-resolver-rules` lives in Chrome's launch flags rather than in the code.
- The mock claude.ai grows the three requests, so the whole flow is rehearsed without an
  account, as every flow before it was.
