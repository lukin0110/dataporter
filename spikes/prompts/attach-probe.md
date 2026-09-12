# Throwaway prompt — does Hermes reach our Chrome? (Q1, Q2)

Not a skill and not a migration; `11`'s `SKILL.md` is the real thing.

**Rung a of Q1 does not need this prompt.** `dataporter doctor` already runs a
`-z` task that must come back having listed *our* claude.ai tab, and refuses to pass when
Hermes answered from a browser of its own — so `doctor`'s `hermes attaches to our Chrome`
line passing *is* rung a answered. This prompt is for the two rungs below it, and for Q2,
which `doctor` cannot answer because it never navigates.

The **prompt is identical on every rung** — what changes is how Hermes is invoked, which is
the point: if the text below works under `hermes serve` and not under `-z`, the difference
is the invocation, not the instructions. See [`../README.md`](../README.md) for the
invocations.

Answers land in [`../../docs/hermes-attach.md`](../../docs/hermes-attach.md).

---

You are attached to a Chrome that is already running and already signed in to claude.ai.
Do not sign in, do not open a new browser, and do not visit any URL outside
`https://claude.ai/new` and `https://claude.ai/chat/<uuid>`.

Do exactly this, in order, and do not skip a step because you expect its answer:

1. List the browser's open tabs. Report the count and each tab's URL.
2. Navigate to `https://claude.ai/new`.
3. List the browser's open tabs again. Report the count and each tab's URL.
4. Run this shell command and report its output verbatim:

   ```
   dataporter browser probe
   ```

5. Take one snapshot of the page and report, in one sentence each and with no page text
   quoted: whether a message composer is present, and whether the page looks signed in.

Then print exactly one JSON object and nothing after it:

```json
{
  "outcome": "completed",
  "last_step": "attach_probe",
  "tabs_before": 0,
  "tabs_after": 0,
  "urls_after": [],
  "reused_existing_tab": true,
  "probe_ok": true,
  "actions": 0
}
```

Rules:

- If you cannot see the browser at all, print the same object with
  `"outcome": "failed"`, `"last_step": "attach"` and an `"error"` object saying what the
  browser tool reported. That answer is the finding; do not work around it by launching
  your own browser.
- Never quote a message, a chat title, or the signed-in account's name or email.
