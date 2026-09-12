# Throwaway prompt — one conversation, end to end

The acceptance criterion of `10`: *one conversation was created by a Hermes `-z` run using
only `browser_*` tools plus our helpers, and its result JSON validated as a
`HermesResult`*. Still throwaway — it hard-codes one conversation's seed paths, makes no
decisions about which conversation to migrate, and has none of `11`'s recovery protocol.

Run it after `attach-probe.md` has answered Q1, and after the hand-driven conversation in
[`../README.md`](../README.md) has proved the same steps work without an agent. Substitute
the two `SEED` paths before running.

---

You are attached to a Chrome signed in to a throwaway claude.ai account. You may only
visit `https://claude.ai/new` and `https://claude.ai/chat/<uuid>`.

Your job is to put two seed parts into one new conversation, verifying every step rather
than assuming it worked.

1. Run `dataporter browser close-extra-tabs` and report its JSON.
2. Navigate to `https://claude.ai/new`.
3. Run `dataporter browser probe`. Continue only if `composer_present` is true,
   `composer_chars` is `0` and `logged_in` is true. If it is not, stop and print the
   failure object below.
4. Run `dataporter browser paste --seed SEED_PART_1`. Continue only if the
   object says `"ok": true`. Do **not** retype the seed yourself under any circumstances —
   the seed must never pass through your own output.
5. Submit the message the way a person would: press Enter in the composer, or click the
   send control. Then run `browser probe` again and continue only if `composer_chars` is
   back to `0`.
6. Run `dataporter browser await-response --expect PART_1_TOKEN`, where the
   token is the acknowledgement string at the end of the seed. Continue only if the object
   says the expected string was found.
7. Run `browser probe` and record the `conversation_id`. If it is `null`, wait five seconds
   and probe again, up to six times, then record what you saw.
8. Repeat steps 4–6 for `SEED_PART_2` and its own token.

Finish by printing exactly one JSON object and nothing after it:

```json
{
  "outcome": "completed",
  "conversation_id": "the uuid from step 7, or null",
  "last_step": "await_response_part_2",
  "chunks_acked": 2,
  "actions": 0
}
```

If you stop early, print the same object with `"outcome"` set to `"failed"`,
`"needs_human"` or `"rate_limited"`, `"last_step"` set to the step you stopped at,
`"chunks_acked"` set to how many acknowledgements you actually saw, and an `"error"`
object of `{"category": "...", "detail": "..."}`. A truthful `failed` is the useful
outcome; an invented `completed` wastes the spike.

Never quote a message, a chat title, or the account's name or email, in your reasoning or
in your answer.
