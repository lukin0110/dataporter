# Claude Account Migration via Hermes

## 1. Goal

Build an experimental migration tool that moves conversation history from one Claude account to another.

The source is a **Claude data export**. The destination is a separate Claude account.

The migration is performed by **Hermes using agentic browser automation**. Hermes operates the destination Claude web application as a user would, creating the initial chats and reconstructing their conversation history.

```text
Claude Account A
      │
      │ export
      ▼
Claude Export
      │
      ▼
Migration / Hermes
      │
      │ agentic browser
      ▼
Claude Account B

```

The experiment is specifically intended to determine whether an agentic browser can reliably reconstruct an account's conversation history in another Claude account.

## 2. Core approach

The system has two distinct components:

### Import/parser

Responsible for turning the Claude export into structured conversations.

### Hermes agent

Responsible for interacting with the destination Claude web application.

The importer does **not** attempt to directly manipulate Claude's internal database or undocumented backend APIs.

Hermes uses the normal Claude user interface to:

1. authenticate to the destination account;
2. create a new chat;
3. populate the chat with the required initial context;
4. send the required messages;
5. verify that the resulting chat exists;
6. continue with the next conversation.

## 3. Why initial chats

A source conversation cannot necessarily be reproduced by simply pasting its entire history into a newly created Claude chat.

The migration should therefore use an **initial-chat strategy**.

For each source conversation, generate a migration seed that gives Claude enough context to reconstruct the original conversation.

Example:

```text
This is a migrated conversation.

Original conversation:
<conversation title>

The following is the historical conversation:

User:
...

Assistant:
...

Continue to preserve this conversation as historical context.

```

The exact seed format should be treated as an implementation detail and evaluated experimentally.

The important requirement is that the resulting destination chat contains enough information to make the historical conversation usable.

## 4. Hermes

Hermes is the agentic browser responsible for interacting with Claude.

Hermes must be able to:

- open Claude;
- identify the destination account's logged-in state;
- create a new chat;
- locate the message input;
- enter the migration seed;
- submit it;
- wait for Claude to respond;
- detect completion;
- identify the resulting conversation;
- recover from common UI failures.

Hermes should operate from the perspective of a normal user interacting with the Claude web application.

## 5. Browser automation

The browser agent should not depend on brittle absolute coordinates.

Prefer:

1. accessible labels;
2. DOM elements;
3. semantic selectors;
4. visible text;
5. browser-agent reasoning.

The agent must be able to adapt to minor UI changes.

Where possible, each important action should have an explicit verification step.

Example:

```text
CREATE CHAT
    ↓
verify chat composer exists
    ↓
ENTER SEED
    ↓
verify text was entered
    ↓
SUBMIT
    ↓
verify message appeared
    ↓
wait for response
    ↓
verify response completed

```

## 6. Migration workflow

### Phase 1 — Analyse export

Parse the Claude export and produce:

```text
Conversation
├── source ID
├── title
├── timestamps
├── messages
└── attachments

```

Determine which conversations can be migrated and which contain unsupported data.

### Phase 2 — Generate migration seeds

For each conversation, create a seed suitable for starting a new Claude chat.

Seeds should preserve:

- conversation title;
- chronological message order;
- user messages;
- assistant messages;
- relevant metadata;
- references to attachments where they cannot be directly reproduced.

### Phase 3 — Hermes execution

Hermes processes conversations sequentially.

For each conversation:

```text
open Claude
  ↓
create new chat
  ↓
enter migration seed
  ↓
submit
  ↓
wait for completion
  ↓
verify
  ↓
record destination conversation

```

### Phase 4 — Resume

The migration state records which conversations have been completed.

If Hermes crashes or the browser session ends, the migration can continue from the last known state.

## 7. Migration state

Maintain a local migration state:

```json
{
  "source-conversation-id": {
    "title": "Example conversation",
    "status": "completed",
    "destination": {
      "conversation_id": "..."
    }
  }
}

```

Possible statuses:

- `pending`
- `running`
- `completed`
- `partial`
- `failed`

The state must be updated after every successfully verified migration.

## 8. Browser session

The destination Claude account must be explicitly authenticated before migration begins.

The tool should support an interactive authentication step:

```bash
hermes-claude-migrate login

```

Hermes then opens the Claude web application and allows the user to authenticate normally.

The migration should reuse that browser session.

The tool must not request or store the user's Claude password.

## 9. Dry run

Provide:

```bash
hermes-claude-migrate import ./claude-export --dry-run

```

This should parse the export and show:

```text
Conversations found: 127
Messages:             4,821
Attachments:             36

Migratable:           124
Unsupported:             3

```

No Claude account should be modified during a dry run.

## 10. Migration execution

Actual migration:

```bash
hermes-claude-migrate import ./claude-export

```

Example output:

```text
Claude migration

127 conversations found

[██████████████░░░░░░] 91/127

Completed: 89
Partial:    1
Failed:     1
Pending:   36

```

Do not print conversation contents during normal operation.

## 11. Agent verification

Hermes must verify important actions instead of assuming that clicks succeeded.

For example, after submitting a seed:

**Bad:**

```text
click Send
sleep 5
continue

```

**Preferred:**

```text
click Send
↓
observe new user message
↓
wait for Claude response
↓
detect generation completion
↓
verify response exists
↓
continue

```

The agent should detect and recover from:

- failed clicks;
- missing composer;
- unexpected dialogs;
- login expiry;
- rate limiting;
- generation failures;
- network errors;
- page navigation;
- Claude UI changes.

## 12. Human intervention

The experiment should allow Hermes to pause and request human intervention when it cannot safely proceed.

Examples:

- authentication required;
- CAPTCHA;
- unexpected security challenge;
- ambiguous UI state;
- unrecoverable browser error.

After intervention, the migration should resume rather than restart.

## 13. Rate limiting and pacing

The migration should deliberately operate at a conservative pace.

The goal of the experiment is **reliability**, not maximum throughput.

Configurable parameters should include:

- delay between conversations;
- maximum retries;
- timeout;
- maximum conversations per run.

## 14. Attachments

Attachments should initially be classified into:

1. directly reproducible;
2. reproducible by uploading through the Claude UI;
3. unsupported.

Where Claude allows an attachment to be uploaded through the normal UI, Hermes should be able to perform that upload.

Unsupported attachments must be recorded rather than silently ignored.

## 15. Fidelity

There are two different fidelity targets.

### Structural fidelity

The destination contains:

- the same conversations;
- equivalent titles;
- equivalent chronological history;
- equivalent message content where possible.

### Semantic fidelity

Claude can understand and work with the migrated conversation as historical context.

The experiment should prioritize **semantic usability** over perfect reproduction of internal Claude metadata that cannot be controlled through the UI.

## 16. Verification report

At the end of a migration:

```text
Claude migration complete

Source conversations:       127
Created:                    124
Partial:                      2
Failed:                       1

Messages represented:      4,821
Attachments migrated:         31

Browser actions:           1,842
Retries:                      17
Human interventions:          2

```

For each failure, record:

- source conversation;
- migration status;
- last successful step;
- error;
- whether retrying is recommended.

## 17. Safety boundaries

The browser agent is permitted to interact with the destination Claude account only for the migration.

It must not:

- delete source conversations;
- modify unrelated destination conversations;
- change account settings;
- modify billing;
- change security settings;
- send messages to unrelated conversations;
- perform actions outside the migration workflow.

Before destructive or account-level actions, Hermes must stop and request human confirmation.

## 18. Initial experiment

Do not start with the entire export.

First run a controlled migration of approximately **5–10 conversations** covering:

- short conversation;
- long conversation;
- conversation with code;
- conversation with attachments;
- conversation containing multiple turns.

Evaluate:

1. Can Hermes reliably create chats?
2. Can it reliably submit large migration seeds?
3. Does Claude correctly understand the reconstructed history?
4. How often does the browser agent require recovery?
5. How much human intervention is required?
6. What Claude UI limitations prevent faithful migration?

Only after this succeeds should the experiment be scaled to the complete export.

## 19. Success criteria

The experiment is successful if Hermes can take a Claude export and automatically reconstruct a useful representation of its conversations in another Claude account through the Claude web interface.

The primary metric is:

> **How many source conversations can be migrated successfully without human intervention?**

Secondary metrics:

- semantic fidelity;
- migration speed;
- browser reliability;
- recovery rate;
- attachment coverage;
- number of manual interventions.

