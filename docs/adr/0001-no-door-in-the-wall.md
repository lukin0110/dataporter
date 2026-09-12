# No door in the wall

The helpers refuse every URL that is not `https://claude.ai/new` or
`https://claude.ai/chat/<id>`, and only the test suite substitutes that surface, in
process. The mock (brief `02`, §21) has to be reached at that host. We decided that the
tool gets no host setting: Chrome is pointed at the mock through operator configuration
alone — the browser's extra arguments map the host to the mock and trust its key — so the
code under rehearsal is the code that ships, byte for byte (§22).

## Considered

- A `browser.host` setting. Easier to configure, but a door in the wall that ships, and a
  typo in it points a real run at a real host.
- An environment override honoured only under a test flag. The same door, hidden.

## Consequences

- The mock serves TLS as `claude.ai` and prints the exact lines an operator pastes (§21).
- The tool cannot tell a rehearsal from a real run, so the mock's ledger is the witness a
  rehearsal record reconciles against (§25).
