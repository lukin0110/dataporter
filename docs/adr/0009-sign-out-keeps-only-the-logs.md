# Sign-out keeps only the logs

`session logout` deleted a browser profile and reported success. An account home holds three
other things: the open ask, whatever a fetch staged on its way to the store, and the logs.
The staging directory is the interesting one — `45`'s download lands there before it is
verified and filed, and `browser/download.py` says outright that an interrupted run's
`.crdownload` is left where it fell. So a command called *logout* could remove the key and
leave the account's own export sitting unencrypted beside the lock.

So **sign-out removes the session, the open ask and what a fetch staged, and keeps the
logs** (brief 08 §83). The logs stay because they are the record of what was done rather
than the means of doing it again, and §10's rule — no title, no message, no address in a
log, at any verbosity — is what makes keeping them safe rather than merely convenient. The
ask goes because it is a promise the tool cannot keep once the session is gone. The staging
goes because it is the account's data and nothing else was ever going to sweep it.

It removes those three **by name**, rather than by walking the account home and deleting
whatever is not `logs/`. The sweep is the tempting version: it is true by construction, a
file a later slice adds dies without anybody editing the command, and the sentence in the
brief and the behaviour in the code cannot drift apart. It was rejected because it decides
in advance, and wrongly, for files nobody has thought about yet — including one an operator
put there by hand — and because it moves the decision out of the specs and into whatever
happens to be on disk. Naming the three keeps the decision a decision.

The cost is real and is accepted: the day an account home grows a fifth thing, §83 has to be
read and amended, and nothing fails if it is not. What blunts it is an acceptance criterion
rather than a hope — `63` pins that an account home's children after `login` and `extract`
are exactly `browser-profile`, `ask.json`, `tmp` and `logs`, so a fifth name turns a test
red even though the sign-out itself would not.

## Considered

**Deleting only the profile, as before.** It is what the command did, and it is why this
document exists: a sign-out that leaves the export behind is telling half the truth about
what it removed.

**Keeping the ask.** It is not a credential — §66 keeps no link, and the record holds only
when the ask was made. Keeping it would have preserved the knowledge that one ask is already
open with the vendor, which matters because only one is. It goes anyway, because an account
home after a sign-out should hold a record and not an intention, and because the vendor will
say so at the next ask more reliably than a file the tool kept.

**Sweeping instead of naming**, above.
