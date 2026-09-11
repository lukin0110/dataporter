"""Attachments: what reaches the new chat, and what is written down instead.

`16`'s subject is one sentence of §14 — nothing is silently ignored — and the
tests below are that sentence taken apart:

- the **plan** decides what an attachment is: reproduced in the seed, uploaded
  through the UI, or refused with a reason. `--skip-attachments` and `16`'s
  deduplication are two more ways of reaching the third and the second;
- the **prompt** carries the files to upload, each one once, and nothing else
  about them;
- the **record** accounts for every one of them afterwards, so that
  `uploaded + inline + unsupported + failed` is the number of attachments the
  plan found — the reconciliation `19` reports;
- a **failed upload** is not fatal and is not silent: the conversation is
  `partial`, the file is named, and a retry is recommended.

The first half needs no browser and no Hermes. The second half runs the real
import loop in `world.py`, between the fake Hermes and the modelled page, which
is where "the prompt lists it" and "state says uploaded" stop being separate
claims.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dataporter import cli, state
from dataporter import importer as importing
from dataporter import plan as planning
from dataporter import seed as seeding
from dataporter.config import AttachmentSettings, Settings
from dataporter.errors import Category
from dataporter.exit_codes import ExitCode
from dataporter.export.model import ChatMessage, Conversation, Export
from dataporter.hermes.runner import HermesResult
from dataporter.state import Status
from dataporter.steps import Step
from world import ATTACHED, CHART, INLINED, World, cli_env, completed, result

WHEN = datetime(2024, 5, 3, 9, 0, tzinfo=UTC)
CONVERSATION = "aaaaaaaa-1111-4111-8111-111111111111"


# --------------------------------------------------------------------------- #
# A conversation built to order
# --------------------------------------------------------------------------- #


def message(
    uuid: str = "m1",
    *,
    parent: str | None = None,
    text: str = "hello",
    files: list[dict[str, str]] | None = None,
    attachments: list[dict[str, str]] | None = None,
) -> ChatMessage:
    return ChatMessage.model_validate(
        {
            "uuid": uuid,
            "sender": "human",
            "text": text,
            "created_at": WHEN,
            "parent_message_uuid": parent,
            "files": files or [],
            "attachments": attachments or [],
        }
    )


def conversation(*messages: ChatMessage) -> Export:
    """One conversation whose active path is every message given, in order."""
    return Export(
        conversations=[
            Conversation.model_validate(
                {
                    "uuid": CONVERSATION,
                    "name": "A chat",
                    "created_at": WHEN,
                    "updated_at": WHEN,
                    "chat_messages": list(messages),
                    "current_leaf_message_uuid": messages[-1].uuid,
                }
            )
        ],
        fingerprint="0" * 64,
    )


def settings_for(attachments_dir: Path, **overrides: Any) -> Settings:
    return Settings(
        workspace=attachments_dir.parent,
        attachments=AttachmentSettings(dir=attachments_dir, **overrides),
    )


def planned(export: Export, settings: Settings) -> planning.ConversationPlan:
    return planning.build_plan(export, settings).conversations[0]


def rendered_seed(export: Export, settings: Settings) -> str:
    outcome = seeding.SeedGenerator(settings).seed(export.conversations[0])
    assert outcome.seed is not None
    return "\n".join(chunk.text for chunk in outcome.seed.chunks)


def hermes_result(**fields: Any) -> HermesResult:
    return HermesResult.model_validate(
        {
            "outcome": "completed",
            "conversation_id": "b6f0a2d4-1c88-4e3a-9a1f-2f0e5d7c8b91",
            "last_step": str(Step.DONE),
            "chunks_acked": 1,
            **fields,
        }
    )


# --------------------------------------------------------------------------- #
# `--skip-attachments`
# --------------------------------------------------------------------------- #


def test_skipping_turns_a_class_2_file_into_class_3(attachments_dir: Path) -> None:
    (attachments_dir / "chart.png").write_bytes(b"bytes")
    export = conversation(message(files=[{"file_name": "chart.png"}]))

    item = planned(export, settings_for(attachments_dir, skip=True))

    entry = item.attachments[0]
    assert entry.klass == "unsupported"
    assert entry.reason == planning.SKIPPED_BY_FLAG
    # Nothing that describes a file about to be uploaded survives the refusal.
    assert entry.source_path is None
    assert entry.sha256 is None
    assert planning.upload_paths(item) == []


def test_a_skipped_file_is_not_promised_by_the_seed(attachments_dir: Path) -> None:
    """The seed says what the chat will hold. A file nobody uploads is not it."""
    (attachments_dir / "chart.png").write_bytes(b"bytes")
    export = conversation(message(files=[{"file_name": "chart.png"}]))

    text = rendered_seed(export, settings_for(attachments_dir, skip=True))

    assert "[File: chart.png — not reproduced: skipped_by_flag]" in text
    assert "attached to this chat" not in text


def test_skipping_does_not_touch_an_inline_attachment(attachments_dir: Path) -> None:
    """Class 1 is text in the seed, not an upload: the flag has nothing to say
    about it."""
    export = conversation(
        message(attachments=[{"file_name": "notes.txt", "extracted_content": "seen"}])
    )

    item = planned(export, settings_for(attachments_dir, skip=True))

    assert item.attachments[0].klass == "inline"


# --------------------------------------------------------------------------- #
# One file, one upload
# --------------------------------------------------------------------------- #


def test_the_same_bytes_on_two_messages_are_uploaded_once(
    attachments_dir: Path,
) -> None:
    (attachments_dir / "chart.png").write_bytes(b"bytes")
    export = conversation(
        message("m1", files=[{"file_name": "chart.png"}]),
        message("m2", parent="m1", files=[{"file_name": "chart.png"}]),
    )

    item = planned(export, settings_for(attachments_dir))

    first, second = item.attachments
    assert [entry.klass for entry in item.attachments] == ["upload", "upload"]
    assert first.duplicate_of is None
    assert second.duplicate_of == "chart.png"
    assert first.sha256 == second.sha256
    # One path in the prompt, and it is the one that is not a duplicate.
    assert planning.upload_paths(item) == [first.source_path]


def test_a_duplicate_is_named_in_the_seed_as_it_was_uploaded(
    attachments_dir: Path,
) -> None:
    """Two names, identical bytes, one chip. The second message refers to the
    chip the chat has rather than to one nobody uploaded."""
    (attachments_dir / "chart.png").write_bytes(b"bytes")
    (attachments_dir / "copy.png").write_bytes(b"bytes")
    export = conversation(
        message("m1", files=[{"file_name": "chart.png"}]),
        message("m2", parent="m1", files=[{"file_name": "copy.png"}]),
    )
    settings = settings_for(attachments_dir)

    item = planned(export, settings)
    text = rendered_seed(export, settings)

    assert item.attachments[1].duplicate_of == "chart.png"
    assert text.count("[File: chart.png — attached to this chat]") == 2
    assert "copy.png" not in text


def test_a_duplicate_does_not_consume_the_per_chat_cap(attachments_dir: Path) -> None:
    """The cap counts what is uploaded, and a duplicate uploads nothing."""
    (attachments_dir / "chart.png").write_bytes(b"bytes")
    (attachments_dir / "other.png").write_bytes(b"different")
    export = conversation(
        message("m1", files=[{"file_name": "chart.png"}]),
        message("m2", parent="m1", files=[{"file_name": "chart.png"}]),
        message("m3", parent="m2", files=[{"file_name": "other.png"}]),
    )

    item = planned(export, settings_for(attachments_dir, max_per_chat=2))

    assert [entry.klass for entry in item.attachments] == [
        "upload",
        "upload",
        "upload",
    ]
    assert len(planning.upload_paths(item)) == 2


def test_a_file_that_cannot_be_read_is_bytes_we_do_not_have(
    attachments_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Between `stat` and the digest, a file can go — a permission, a race with
    whoever is filling the directory, a disk. It is still the reason an operator
    can act on."""
    (attachments_dir / "chart.png").write_bytes(b"bytes")
    export = conversation(message(files=[{"file_name": "chart.png"}]))
    monkeypatch.setattr(planning, "_digest", lambda path: None)

    item = planned(export, settings_for(attachments_dir))

    assert item.attachments[0].klass == "unsupported"
    assert item.attachments[0].reason == planning.BYTES_NOT_IN_EXPORT


def test_a_digest_of_a_file_that_is_not_there_is_nothing(tmp_path: Path) -> None:
    assert planning._digest(tmp_path / "gone.png") is None


# --------------------------------------------------------------------------- #
# What the record says afterwards
# --------------------------------------------------------------------------- #


def test_every_attachment_lands_in_exactly_one_count(attachments_dir: Path) -> None:
    """`16`'s reconciliation, on a conversation with one of everything."""
    (attachments_dir / "chart.png").write_bytes(b"bytes")
    export = conversation(
        message(
            attachments=[{"file_name": "notes.txt", "extracted_content": "seen"}],
            files=[{"file_name": "chart.png"}, {"file_name": "video.mov"}],
        )
    )
    item = planned(export, settings_for(attachments_dir))

    counts = importing.attachments_of(
        item, hermes_result(attachments_uploaded=["chart.png"])
    )

    assert (counts.uploaded, counts.inline, counts.unsupported, counts.failed) == (
        1,
        1,
        1,
        0,
    )
    assert counts.uploaded + counts.inline + counts.unsupported + counts.failed == len(
        item.attachments
    )
    assert [
        (entry.file_name, entry.klass, entry.reason) for entry in counts.detail
    ] == [
        ("notes.txt", "inline", None),
        ("video.mov", "unsupported", planning.TYPE_NOT_ACCEPTED),
    ]


def test_a_refused_upload_is_recorded_with_what_refused_it(
    attachments_dir: Path,
) -> None:
    (attachments_dir / "chart.png").write_bytes(b"bytes")
    export = conversation(message(files=[{"file_name": "chart.png"}]))
    item = planned(export, settings_for(attachments_dir))

    counts = importing.attachments_of(
        item,
        hermes_result(
            outcome="partial",
            attachments_failed=[{"file_name": "chart.png", "error": "upload_rejected"}],
        ),
    )

    assert counts.failed == 1
    assert counts.detail[0].klass == "failed"
    assert counts.detail[0].reason == "upload_rejected"


def test_an_upload_nobody_confirmed_is_not_counted_as_done(
    attachments_dir: Path,
) -> None:
    """Evidence, not intention: a run that says nothing about a file it was
    given has not told us the chat has it."""
    (attachments_dir / "chart.png").write_bytes(b"bytes")
    export = conversation(message(files=[{"file_name": "chart.png"}]))
    item = planned(export, settings_for(attachments_dir))

    counts = importing.attachments_of(item, hermes_result())

    assert counts.uploaded == 0
    assert counts.detail[0].reason == importing.NOT_REPORTED


def test_a_conversation_nothing_ran_reports_its_files_as_not_attempted(
    attachments_dir: Path,
) -> None:
    (attachments_dir / "chart.png").write_bytes(b"bytes")
    export = conversation(message(files=[{"file_name": "chart.png"}]))
    item = planned(export, settings_for(attachments_dir))

    counts = importing.attachments_of(item)

    assert counts.failed == 1
    assert counts.detail[0].reason == importing.NOT_ATTEMPTED


def test_a_duplicate_is_counted_under_the_name_that_was_uploaded(
    attachments_dir: Path,
) -> None:
    """One chip, two references: the agent can only have reported one name."""
    (attachments_dir / "chart.png").write_bytes(b"bytes")
    (attachments_dir / "copy.png").write_bytes(b"bytes")
    export = conversation(
        message("m1", files=[{"file_name": "chart.png"}]),
        message("m2", parent="m1", files=[{"file_name": "copy.png"}]),
    )
    item = planned(export, settings_for(attachments_dir))

    counts = importing.attachments_of(
        item, hermes_result(attachments_uploaded=["chart.png"])
    )

    assert counts.uploaded == 2
    assert counts.detail == []


# --------------------------------------------------------------------------- #
# A failed upload, as the loop reads it
# --------------------------------------------------------------------------- #


def test_a_completed_run_that_could_not_attach_is_partial() -> None:
    mapped = importing.interpret(
        hermes_result(
            attachments_failed=[{"file_name": CHART, "error": "upload_rejected"}]
        ),
        landed=True,
    )

    assert mapped.status is Status.PARTIAL
    assert mapped.error is not None
    assert mapped.error.category is Category.UNSUPPORTED
    assert mapped.error.detail == f"attachment upload failed: {CHART}"
    # Not the category's answer — the class says `unsupported` is permanent, and
    # an upload that was refused once is not.
    assert mapped.error.retry_recommended is True


def test_a_completed_run_with_nothing_failed_is_completed() -> None:
    mapped = importing.interpret(
        hermes_result(attachments_uploaded=[CHART]), landed=True
    )

    assert mapped.status is Status.COMPLETED
    assert mapped.error is None


def test_a_file_name_from_the_agent_cannot_forge_a_line() -> None:
    """The names in the result come from a page and reach `state.json` and the
    report, so they go through the same reduction every borrowed string does."""
    mapped = importing.interpret(
        hermes_result(attachments_failed=[{"file_name": "a\nb", "error": "x"}]),
        landed=True,
    )

    assert mapped.error is not None
    assert mapped.error.detail == "attachment upload failed: a?b"


# --------------------------------------------------------------------------- #
# Acceptance: through the loop
# --------------------------------------------------------------------------- #


def drop_the_chart(world: World, name: str = CHART) -> Path:
    """The bytes an operator supplied, where `03` looks for them."""
    target = world.settings.attachments_dir / ATTACHED
    target.mkdir(parents=True, exist_ok=True)
    path = target / name
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    return path


def seed_text(world: World) -> str:
    return (world.settings.seeds_dir / ATTACHED / "part-01.txt").read_text(
        encoding="utf-8"
    )


def test_a_file_that_is_there_is_uploaded_and_recorded(world: World) -> None:
    """`16`'s first acceptance criterion, end to end."""
    path = drop_the_chart(world)
    world.answers(completed(attachments_uploaded=[CHART]))

    world.run(only=[ATTACHED])

    prompt = world.hermes.one_shots[0].prompt
    assert f"attachments:\n{path}\n" in prompt
    entry = world.entry(ATTACHED)
    assert entry.status is Status.COMPLETED
    assert entry.attachments.uploaded == 1
    assert entry.attachments.inline == 1
    assert entry.attachments.unsupported == 0
    assert entry.attachments.failed == 0
    # The seed tells the new chat which message the file belonged to.
    assert f"[File: {CHART} — attached to this chat]" in seed_text(world)


def test_a_file_that_is_not_there_does_not_degrade_the_conversation(
    world: World,
) -> None:
    """Class 3 was never migratable: recorded, and the migration is still done."""
    world.run(only=[ATTACHED])

    prompt = world.hermes.one_shots[0].prompt
    assert "attachments: none" in prompt
    entry = world.entry(ATTACHED)
    assert entry.status is Status.COMPLETED
    assert entry.error is None
    assert entry.attachments.unsupported == 1
    assert entry.attachments.uploaded == 0
    assert [(item.file_name, item.reason) for item in entry.attachments.detail] == [
        (INLINED, None),
        (CHART, planning.BYTES_NOT_IN_EXPORT),
    ]
    assert f"[File: {CHART} — not reproduced: bytes_not_in_export]" in seed_text(world)


def test_an_upload_that_failed_leaves_a_partial_naming_the_file(world: World) -> None:
    """A chat that is missing one of its files is not a finished migration."""
    drop_the_chart(world)
    world.answers(
        completed(
            attachments_failed=[{"file_name": CHART, "error": "upload_rejected"}],
        )
    )
    world.retries(max_attempts=1)

    world.run(only=[ATTACHED])

    entry = world.entry(ATTACHED)
    assert entry.status is Status.PARTIAL
    assert entry.error is not None
    assert entry.error.category is Category.UNSUPPORTED
    assert entry.error.detail == f"attachment upload failed: {CHART}"
    # The record this failure produces recommends a retry (`interpret`, above);
    # what is on disk afterwards says `false` because `13` has just spent the
    # last attempt on it, which is `13`'s rule and not a statement about the
    # upload.
    assert entry.error.retry_recommended is False
    assert entry.attachments.failed == 1
    assert entry.attachments.detail[-1].reason == "upload_rejected"


def test_a_failed_upload_is_tried_again(world: World) -> None:
    """`16` asks for `retry_recommended: true`, and `13` reads that field as the
    decision: the same conversation is attempted again, in the chat it already
    has, and the file can land the second time."""
    drop_the_chart(world)
    world.retries(max_attempts=2, backoff_s=[0])
    world.answers(
        completed(attachments_failed=[{"file_name": CHART, "error": "chip_not_found"}]),
        completed(attachments_uploaded=[CHART]),
    )

    world.run(only=[ATTACHED])

    assert len(world.hermes.one_shots) == 2
    entry = world.entry(ATTACHED)
    assert entry.status is Status.COMPLETED
    assert entry.attachments.uploaded == 1
    assert entry.attachments.failed == 0


def test_the_counts_reconcile_with_the_plan(world: World) -> None:
    """Every attachment the plan found is in exactly one of the four counts, for
    every conversation the run wrote an entry for."""
    drop_the_chart(world)
    world.answers(completed(attachments_uploaded=[CHART]))

    world.run()

    plan = json.loads(
        (world.settings.workspace / importing.PLAN_FILENAME).read_text(encoding="utf-8")
    )
    found = {item["uuid"]: len(item["attachments"]) for item in plan["conversations"]}
    migration = world.store().load()
    for uuid, entry in migration.items():
        counts = entry.attachments
        assert (
            counts.uploaded + counts.inline + counts.unsupported + counts.failed
            == found[uuid]
        ), uuid
    assert sum(found.values()) == plan["totals"]["attachments"]


def test_the_workspace_explains_where_attachment_bytes_go(world: World) -> None:
    """The directory is empty and the convention is in a spec nobody read."""
    world.run(limit=1)

    readme = (
        world.settings.attachments_dir / importing.ATTACHMENTS_README_FILENAME
    ).read_text(encoding="utf-8")
    assert "attachments/<conversation-uuid>/<file name>" in readme


def test_a_directory_that_cannot_be_made_does_not_end_the_run(world: World) -> None:
    """A migration without attachments is still a migration, and `03` reports
    every file it could not find either way."""
    world.settings.workspace.mkdir(parents=True, exist_ok=True)
    (world.settings.workspace / "attachments").write_text("not a directory")

    summary = world.run(limit=1)

    assert summary.exit_code == ExitCode.OK


def test_a_directory_the_operator_named_is_left_alone(
    world: World, tmp_path: Path
) -> None:
    """`--attachments-dir` points at somebody else's folder, and we do not
    litter in it."""
    theirs = tmp_path / "theirs"
    theirs.mkdir()
    world.settings.attachments = AttachmentSettings(dir=theirs)

    world.run(limit=1)

    assert list(theirs.iterdir()) == []


def test_a_conversation_that_is_not_migrated_still_accounts_for_its_files(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An entry `_create_entries` wrote as `failed` is not an entry with no
    attachments — it is one whose attachments are going nowhere."""
    monkeypatch.setattr(
        importing.Importer,
        "_migrate_all",
        lambda self, chosen, conversations, plan, **kwargs: importing.RunSummary(
            total=len(plan.conversations),
            selected=(),
            outcomes={},
            counts=state.status_counts(self.store.load()),
            exit_code=ExitCode.OK,
        ),
    )
    drop_the_chart(world)
    # The conversation with the files, made unmigratable by a cap nothing fits
    # under, so that `_create_entries` writes it rather than the loop.
    world.settings.seed = world.settings.seed.model_copy(update={"hard_max_chars": 10})

    world.run()

    entry = world.entry(ATTACHED)
    assert entry.status is Status.FAILED
    assert entry.attachments.failed == 1
    assert entry.attachments.detail[-1].reason == importing.NOT_ATTEMPTED


# --------------------------------------------------------------------------- #
# Acceptance: the flag, through the command
# --------------------------------------------------------------------------- #


def test_skip_attachments_uploads_nothing_and_says_why(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli_env(world, monkeypatch)
    drop_the_chart(world)

    outcome = runner.invoke(
        cli.app,
        [
            "import",
            str(world.export),
            "--only",
            ATTACHED,
            "--skip-attachments",
        ],
        catch_exceptions=False,
    )

    assert outcome.exit_code == ExitCode.OK
    assert "attachments: none" in world.hermes.one_shots[0].prompt
    entry = world.entry(ATTACHED)
    assert entry.attachments.uploaded == 0
    assert entry.attachments.detail[-1].reason == planning.SKIPPED_BY_FLAG
    # Recorded in the run, so the report can say skipped rather than unavailable.
    assert world.store().run().runs[-1].selection.skip_attachments is True


def test_without_the_flag_the_same_run_uploads(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli_env(world, monkeypatch)
    path = drop_the_chart(world)
    world.answers(completed(attachments_uploaded=[CHART]))

    runner.invoke(
        cli.app,
        ["import", str(world.export), "--only", ATTACHED],
        catch_exceptions=False,
    )

    assert str(path) in world.hermes.one_shots[0].prompt
    assert world.store().run().runs[-1].selection.skip_attachments is False


def test_a_dry_run_takes_the_flag_and_still_counts_the_files(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--dry-run` answers what a run would do, so the flag has to reach the
    plan it builds — and skipping changes what becomes of an attachment, never
    how many the export has."""
    cli_env(world, monkeypatch)
    drop_the_chart(world)
    arguments = ["import", str(world.export), "--dry-run", "--only", ATTACHED]

    with_flag = runner.invoke(
        cli.app, [*arguments, "--skip-attachments"], catch_exceptions=False
    )
    without = runner.invoke(cli.app, arguments, catch_exceptions=False)

    assert with_flag.exit_code == ExitCode.OK
    assert "Attachments:" in with_flag.stdout
    assert with_flag.stdout == without.stdout
    # And nothing was written: a dry run does not create the workspace.
    assert not (world.settings.workspace / "state.json").exists()


def test_inspect_reports_a_file_the_operator_supplied(
    world: World, runner: CliRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--attachments-dir` is what turns class 3 into class 2, and `inspect` is
    the command whose job is to say so."""
    cli_env(world, monkeypatch)
    drop_the_chart(world)

    outcome = runner.invoke(
        cli.app,
        ["inspect", str(world.export), "--json"],
        catch_exceptions=False,
    )

    plan = json.loads(outcome.stdout)
    item = next(entry for entry in plan["conversations"] if entry["uuid"] == ATTACHED)
    assert [file["klass"] for file in item["attachments"]] == ["inline", "upload"]


def test_a_result_that_mentions_no_attachments_still_runs(world: World) -> None:
    """The two lists are optional in the contract: a run that had no files to
    attach has nothing to say about them."""
    world.answers(result(outcome="completed", conversation_id="c" * 36))

    summary = world.run(limit=1)

    assert summary.exit_code == ExitCode.OK
