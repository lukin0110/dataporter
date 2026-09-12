# The command is `dataporter`

The brief (`01`, §8–§10) writes the command as `hermes-claude-migrate`, and `01` built it
that way, with `HCM_` as the environment prefix. The program is meant to become general
purpose — the same tool will port ChatGPT, Gemini and Copilot exports — and a name that
spells one source and one agent would be wrong the day the second source lands. We decided
that the command, the environment prefix and the tool's internal markers take the package's
own name: the console script is `dataporter`, the environment is `DATAPORTER_…`, the
doctor's nonce is `DATAPORTER-<hex>` and the comments the helpers inject into a page are
`dataporter:*`. The Hermes skill keeps its name, `claude-migrate`, because it names what
the skill does and not the program: a later source gets its own skill beside it, under the
same `dataporter` namespace. The brief's spelling is superseded by this record and not
edited; `specs/README.md` names both.

## Considered

- Keep `hermes-claude-migrate` until a second source exists. The name would then be
  wrong in every prompt, doc and skill at once, on the day there is the most of it.
- Rename the skill as well, to `dataporter`. A skill is one procedure against one site;
  the name that will still be right with four sources is the one that says which.

## Consequences

- Records written before the rename — the briefs, `docs/rehearsal-01.md` — keep the old
  name. A record is what was, and a rehearsal record in particular names the tool that ran.
- `PROGRAM_NAME` in `dataporter/__init__.py` is the one place the command is spelled in
  code, and the packaged skill's `helper` row, the one literal copy, is tested against it.
- Anything source-specific that is added later is named for its source (`chatgpt-…`),
  never for the program.
