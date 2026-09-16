# Signing out

**Brief 08.** Section numbers continue from [`07-claude-sign-in.md`](07-claude-sign-in.md),
which ends at §80, so that `§N` names exactly one section anywhere in this repository. The
words used here are defined in [`CONTEXT.md`](../CONTEXT.md).

## 81. Goal

Make **signing out mean what it says**. `session logout` deletes a browser profile and
reports success, and brief 07 §74 describes it doing exactly that. What it leaves behind is
the rest of the account home: the open ask, and whatever a fetch staged on its way to the
store. That second one is the account's own export — the archive the vendor produced, or
half of it — sitting unencrypted in a directory whose session has just been deleted.

A command that removes the key and leaves the contents is not a sign-out. This brief makes
it one, and gives it the name a person types:

```bash
dataporter logout --source claude --account work

```

This amends §74, which says the tool holds a browser profile afterwards and that
`session logout` deletes it. The first half stands: the tool still holds no credential, no
token and no expiry. The second half is replaced — there is no `session logout` any more,
and what replaces it deletes more than a profile.

Nothing about the store, the snapshot or the archive changes. A snapshot that was filed
stays filed; sign-out never reaches into the store.

## 82. The command

`--account` is required. There is no form of this command that means the destination, and
no default that could make it mean the wrong account. `--source` defaults to `claude` as it
does for `extract`.

It ends in one of two ways, and both are golden (`specs/README.md`), as brief 03's, brief
06's and brief 07's are. Signed out:

```text
Signed out of Claude — work
Removed ~/.dataporter/accounts/claude/work/, except its logs.

```

Or there was nothing there to remove — the account was never signed in, or this is the
second time the command has been run:

```text
Nothing to remove: ~/.dataporter/accounts/claude/work/ has no session.

```

Both exit `0`. Sign-out states an end, not an act: when the end is already true, the
command has nothing to do and no reason to complain. That also means a mistyped label
succeeds quietly, which is the same bargain `session status` already makes — an account
label is a label, and nothing registers one.

There is no confirmation. The cost of an unwanted sign-out is a fresh link in the vendor's
mailbox; the cost of friction on a command whose job is to remove a session is worse.

## 83. What it removes, and what it keeps

The account home holds four things, and sign-out sorts them in one line: **everything the
account home holds, except its logs.**

```text
~/.dataporter/accounts/claude/work/
├── browser-profile/   the source session          removed
├── ask.json           the open ask                removed
├── tmp/               what a fetch staged         removed
└── logs/              the run log, the trace,     kept
                       the action log
```

The logs are kept because they are the record of what was done, and hold no message, no
title and no address — §10's rule is what makes that true, and what makes a log safe to
keep after the session it describes is gone. The command writes one of its own on the way
past, so an account home that has been signed out of still has a `logs/` and nothing else.

The open ask goes because it is the paperwork of a session that no longer exists: the tool
cannot fetch against it without signing in again, and one ask is open per account at a time.
Its cost is recorded rather than hidden — a person who signs out mid-ask has forfeited that
ask, and will be told by the vendor rather than by us when they open the next one.

What a fetch staged goes because it is the account's data. `45`'s download lands there
before it is verified and filed, and an interrupted run leaves it; nothing swept it until
now.

Sign-out removes these **by name**, not by sweeping the directory of everything that is not
`logs/`. A sweep would be true by construction and would also delete whatever a later slice
put there without anybody deciding it should go. Naming them makes the decision a decision,
and the day a slice adds a fifth thing to the account home, this section is where it says
whether it survives.

A partial failure — a permission, a file something else is holding — stops at the first one
with exit `2`, leaving the rest. Rerunning finishes the job, because the command is the same
command whether it is run once or twice.

## 84. Local, and said so

Sign-out is local. The vendor is not told, the session is not revoked, and an account signed
in on another machine is untouched. What the command destroys is this machine's ability to
act as the account; what it cannot destroy is the vendor's record that the session existed.

This is by construction and not an omission. Revoking would mean driving the app to find a
menu and a button — a surface far wider than §73's sign-in page, on a session that is
working, which is the case where sign-out is least needed. It would also fail exactly when
it is wanted most: a session that is wedged or expired is one the tool cannot drive to
anything.

`docs/LIMITATIONS.md` carries this as a limitation *by construction*, beside the sign-in it
mirrors.

## 85. The browser that is still open

The window from `login` is often still up when a person decides to sign out, and deleting a
profile out from under a running Chrome leaves a half-written directory and a browser still
holding the session in memory.

So the command looks at the debug port before it deletes anything. A browser that the
profile's own marker names — same port, same browser id, the window **we** opened on **this**
profile — is closed first, silently, the way `login` and `session status` close theirs. Any
other browser answering on that port is refused with exit `2`, because Chrome does not say
which profile it holds and a guess there deletes the wrong thing.

The check runs first, before anything is removed. A refusal that arrived after the ask was
already gone would be a sign-out that half happened and reported failure.

## 86. What the destination loses

`session logout` had a form with no account that meant the destination's profile, and
`session status` has one still. Both go: the session commands are for source accounts, and
each names one. **§35 is amended by this section** — it says these commands do not take an
account and go on meaning the destination when the option is absent, and after this one of
them is gone and the other requires it.

`login` keeps its destination form — the migration needs a signed-in destination and that is
how it gets one. So the destination can be signed in and then neither reported on nor cleared
by any command. That is accepted rather than overlooked: the destination's profile lives
inside the workspace, which `docs/runbook.md` already removes whole, and a migration that
finds itself signed out says so and names `login`.

One consequence is not cosmetic. `53` tells a person whose window closed under a link to run
`session status` and see for themselves; for the destination that now names a command that
cannot be run, so the remedy becomes `login` where there is no account to name. A remedy
that cannot be typed is worse than a blunter one that can.

**§23 is amended by this section**: its protocol loses the `session status` and
`session logout` steps, which had no account to name. The extraction protocol keeps both —
it passed a source and an account all along.

## 87. Later

Deliberately left, and unclaimed until one of them is built:

- **Revoking a session from the tool.** Sign-out is local by construction (§84). This
  replaces §80's bullet, which named a command that no longer exists.
- **Signing the destination out.** §86 leaves the workspace's own profile to `rm -rf`.
  A command for it is wanted the day the workspace stops being the disposable thing it is.
- **Sweeping what a fetch staged, without signing out.** `tmp/` is cleared by sign-out
  today and by nothing else; an interrupted run still leaves its download behind for as
  long as the account stays signed in.
- **Signing out of every account at once.** One account per invocation, because `--account`
  is required and means it. A person with six accounts runs it six times.
