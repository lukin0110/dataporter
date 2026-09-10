# NN — Title

**Kind:** Implementation spec — how this gets built. Living document.
**Implements:** [Brief](../01-initial-brief.md) §N, §N
**Depends on:** [NN](NN-slug.md), or `nothing`
**Enables:** [NN](NN-slug.md), or `nothing yet`
**Status:** Not started | In progress | Done

## Goal

Two or three sentences. What this slice delivers, and what it is not. A slice should be
buildable in one sitting; if it is not, split it.

## In scope

Concrete, buildable items. Name commands, flags, files, types, config keys and exact
output — this is the document where specifics belong. Where the brief gives an example
output, quote it and treat it as the golden string.

## Out of scope

What a reader might reasonably expect here but will find in another slice. Link it.

## Design notes

Decisions made and why, especially anywhere this slice resolves something the brief left
open ("treated as an implementation detail", "evaluated experimentally"). If a decision
could reasonably have gone the other way, say what was rejected.

## Acceptance criteria

Checkable statements. Each one should be answerable yes or no by running something, not by
reading the code and forming an opinion. Prefer golden-file tests for output formats.

## Risks

What could make this slice wrong, and what would surface it.
