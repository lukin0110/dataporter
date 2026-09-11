"""Classification.

The four acceptance criteria of `03` are the first four sections; everything after
them covers a rule the spec states but the fixture does not exercise.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from dataporter import plan as planning
from dataporter.config import AttachmentSettings, SeedSettings, Settings
from dataporter.export import load_export
from dataporter.export.model import ChatMessage, Conversation, Export

WHEN = datetime(2024, 5, 3, 9, 0, tzinfo=UTC)

ATTACHMENT_CONVERSATION = "dd000004-4444-4444-8444-444444444444"
BRANCH_CONVERSATION = "ee000005-5555-4555-8555-555555555555"
EMPTY_CONVERSATION = "ff000006-6666-4666-8666-666666666666"


def settings_for(attachments_dir: Path, **overrides: object) -> Settings:
    """Settings that look at `attachments_dir` and nothing else machine-specific."""
    return Settings(
        workspace=attachments_dir.parent,
        attachments=AttachmentSettings(dir=attachments_dir, **overrides),
    )


def plan_of(
    export_dir: Path, attachments_dir: Path, **overrides: object
) -> planning.MigrationPlan:
    return planning.build_plan(
        load_export(export_dir), settings_for(attachments_dir, **overrides)
    )


def find(plan: planning.MigrationPlan, uuid: str) -> planning.ConversationPlan:
    return next(item for item in plan.conversations if item.uuid == uuid)


# --------------------------------------------------------------------------- #
# Acceptance: migratability
# --------------------------------------------------------------------------- #


def test_the_fixture_has_exactly_one_unsupported_conversation(
    export_dir: Path, attachments_dir: Path
) -> None:
    plan = plan_of(export_dir, attachments_dir)
    unsupported = [item for item in plan.conversations if not item.migratable]
    assert [item.uuid for item in unsupported] == [EMPTY_CONVERSATION]
    assert unsupported[0].reasons == [planning.EMPTY_CONVERSATION]


def test_the_branch_conversation_is_migratable_with_one_branch_dropped(
    export_dir: Path, attachments_dir: Path
) -> None:
    branch = find(plan_of(export_dir, attachments_dir), BRANCH_CONVERSATION)
    assert branch.migratable
    assert branch.reasons == ["branches_dropped:1"]
    assert branch.off_path_count == 1
    assert branch.message_count == 4


# --------------------------------------------------------------------------- #
# Acceptance: attachment classes
# --------------------------------------------------------------------------- #


def test_an_attachment_with_extracted_content_is_inline(
    export_dir: Path, attachments_dir: Path
) -> None:
    attachments = find(
        plan_of(export_dir, attachments_dir), ATTACHMENT_CONVERSATION
    ).attachments
    inline = next(item for item in attachments if item.klass == "inline")
    assert inline.file_name == "q3-summary.txt"
    assert inline.source_path is None


def test_a_file_with_no_bytes_is_unsupported(
    export_dir: Path, attachments_dir: Path
) -> None:
    attachments = find(
        plan_of(export_dir, attachments_dir), ATTACHMENT_CONVERSATION
    ).attachments
    missing = next(item for item in attachments if item.file_name == "q3-chart.png")
    assert missing.klass == "unsupported"
    assert missing.reason == planning.BYTES_NOT_IN_EXPORT


def test_dropping_the_bytes_in_flips_the_file_to_upload(
    export_dir: Path, attachments_dir: Path
) -> None:
    target = attachments_dir / ATTACHMENT_CONVERSATION
    target.mkdir()
    (target / "q3-chart.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    attachments = find(
        plan_of(export_dir, attachments_dir), ATTACHMENT_CONVERSATION
    ).attachments
    upload = next(item for item in attachments if item.file_name == "q3-chart.png")
    assert upload.klass == "upload"
    assert upload.source_path == (target / "q3-chart.png").resolve()
    assert upload.file_size == 8


def test_bytes_beside_the_directory_are_found_too(
    export_dir: Path, attachments_dir: Path
) -> None:
    """`<dir>/<name>` is the fallback when the operator did not sort by chat."""
    (attachments_dir / "q3-chart.png").write_bytes(b"x")
    attachments = find(
        plan_of(export_dir, attachments_dir), ATTACHMENT_CONVERSATION
    ).attachments
    upload = next(item for item in attachments if item.file_name == "q3-chart.png")
    assert upload.klass == "upload"
    assert upload.source_path == (attachments_dir / "q3-chart.png").resolve()


def test_the_same_file_in_files_and_files_v2_is_one_attachment(
    export_dir: Path, attachments_dir: Path
) -> None:
    """The fixture carries `q3-chart.png` in both; the UI showed it once."""
    attachments = find(
        plan_of(export_dir, attachments_dir), ATTACHMENT_CONVERSATION
    ).attachments
    assert [item.file_name for item in attachments] == [
        "q3-summary.txt",
        "q3-chart.png",
    ]


# --------------------------------------------------------------------------- #
# Acceptance: determinism and totals
# --------------------------------------------------------------------------- #


def test_two_plans_of_one_export_serialise_identically(
    export_dir: Path, attachments_dir: Path
) -> None:
    first = plan_of(export_dir, attachments_dir)
    second = plan_of(export_dir, attachments_dir)
    assert first.model_dump_json() == second.model_dump_json()


def test_the_plan_carries_the_export_fingerprint(
    export_dir: Path, attachments_dir: Path
) -> None:
    export = load_export(export_dir)
    plan = planning.build_plan(export, settings_for(attachments_dir))
    assert plan.export_fingerprint == export.fingerprint
    assert len(plan.export_fingerprint) == 64


def test_migratable_and_unsupported_account_for_every_conversation(
    export_dir: Path, attachments_dir: Path
) -> None:
    totals = plan_of(export_dir, attachments_dir).totals
    assert totals.migratable + totals.unsupported == totals.conversations
    assert totals.conversations == 6
    assert totals.messages == 50
    assert totals.attachments == 2


# --------------------------------------------------------------------------- #
# Rules the fixture does not reach
# --------------------------------------------------------------------------- #


def message(
    uuid: str = "m1",
    *,
    sender: str = "human",
    text: str = "",
    content: list[object] | None = None,
    attachments: list[object] | None = None,
    files: list[object] | None = None,
) -> ChatMessage:
    return ChatMessage.model_validate(
        {
            "uuid": uuid,
            "sender": sender,
            "text": text,
            "content": content or [],
            "attachments": attachments or [],
            "files": files or [],
            "created_at": WHEN,
        }
    )


def one_conversation(*messages: ChatMessage) -> Export:
    conversation = Conversation.model_validate(
        {
            "uuid": "aaaaaaaa-1111-4111-8111-111111111111",
            "name": "A chat",
            "created_at": WHEN,
            "updated_at": WHEN,
            "chat_messages": list(messages),
        }
    )
    return Export(conversations=[conversation], fingerprint="0" * 64)


def only(export: Export, settings: Settings) -> planning.ConversationPlan:
    return planning.build_plan(export, settings).conversations[0]


def test_a_conversation_of_placeholders_has_no_representable_text(
    attachments_dir: Path,
) -> None:
    export = one_conversation(
        message(content=[{"type": "tool_result", "content": "created"}])
    )
    item = only(export, settings_for(attachments_dir))
    assert not item.migratable
    assert item.reasons[0] == planning.NO_REPRESENTABLE_TEXT


def test_a_seed_over_the_hard_cap_is_not_migrated(attachments_dir: Path) -> None:
    export = one_conversation(message(text="x" * 5_000))
    settings = settings_for(attachments_dir)
    capped = settings.model_copy(
        update={"seed": SeedSettings(max_chars=1_000, hard_max_chars=2_000)}
    )
    item = only(export, capped)
    assert not item.migratable
    assert item.reasons[0] == planning.SEED_OVER_HARD_CAP
    assert item.estimated_seed_chars > 2_000
    assert item.chunk_count > 1


def test_an_empty_conversation_reports_no_seed_at_all(
    export_dir: Path, attachments_dir: Path
) -> None:
    """An envelope around nothing is not a seed, so its length is not a number."""
    empty = find(plan_of(export_dir, attachments_dir), EMPTY_CONVERSATION)
    assert (empty.estimated_seed_chars, empty.chunk_count) == (0, 0)


def test_limitations_are_reported_beside_a_blocking_reason(
    attachments_dir: Path,
) -> None:
    export = one_conversation(
        message(
            content=[
                {"type": "thinking", "thinking": "hmm"},
                {"type": "tool_result", "content": "x"},
            ]
        )
    )
    item = only(export, settings_for(attachments_dir))
    assert item.reasons == [planning.NO_REPRESENTABLE_TEXT, "thinking_omitted:1"]


UNSUPPORTED_TYPES = ["archive.zip", "installer.exe", "notes"]


@pytest.mark.parametrize("file_name", UNSUPPORTED_TYPES, ids=lambda value: str(value))
def test_a_type_that_is_not_accepted_is_refused_before_the_bytes_are_looked_for(
    attachments_dir: Path, file_name: str
) -> None:
    (attachments_dir / file_name).write_bytes(b"x")
    export = one_conversation(message(text="hi", files=[{"file_name": file_name}]))
    item = only(export, settings_for(attachments_dir))
    assert item.attachments[0].klass == "unsupported"
    assert item.attachments[0].reason == planning.TYPE_NOT_ACCEPTED
    assert item.attachments[0].source_path is None


def test_a_mime_type_types_a_file_whose_name_has_no_suffix(
    attachments_dir: Path,
) -> None:
    (attachments_dir / "notes").write_bytes(b"hello")
    export = one_conversation(
        message(
            text="hi",
            attachments=[{"file_name": "notes", "file_type": "text/plain"}],
        )
    )
    item = only(export, settings_for(attachments_dir))
    assert item.attachments[0].klass == "upload"


def test_a_file_over_the_size_limit_is_unsupported(attachments_dir: Path) -> None:
    (attachments_dir / "big.pdf").write_bytes(b"x" * 100)
    export = one_conversation(message(text="hi", files=[{"file_name": "big.pdf"}]))
    item = only(export, settings_for(attachments_dir, max_bytes=10))
    assert item.attachments[0].klass == "unsupported"
    assert item.attachments[0].reason == planning.TOO_LARGE
    assert item.attachments[0].file_size == 100


def test_uploads_past_the_per_chat_cap_are_unsupported_in_document_order(
    attachments_dir: Path,
) -> None:
    for index in range(4):
        # Distinct bytes: identical ones are one upload and three duplicates
        # (`16`), which is a different rule and has its own tests.
        (attachments_dir / f"f{index}.png").write_bytes(b"x" * (index + 1))
    export = one_conversation(
        message(text="hi", files=[{"file_name": f"f{index}.png"} for index in range(4)])
    )
    item = only(export, settings_for(attachments_dir, max_per_chat=2))
    assert [entry.klass for entry in item.attachments] == [
        "upload",
        "upload",
        "unsupported",
        "unsupported",
    ]
    assert item.attachments[3].reason == planning.TOO_MANY_FOR_CHAT
    assert item.attachments[3].source_path is None


def test_an_inline_attachment_does_not_consume_the_upload_cap(
    attachments_dir: Path,
) -> None:
    (attachments_dir / "chart.png").write_bytes(b"x")
    export = one_conversation(
        message(
            text="hi",
            attachments=[{"file_name": "notes.txt", "extracted_content": "seen it"}],
            files=[{"file_name": "chart.png"}],
        )
    )
    item = only(export, settings_for(attachments_dir, max_per_chat=1))
    assert [entry.klass for entry in item.attachments] == ["inline", "upload"]


ESCAPING_NAMES = [
    "../outside.png",
    "..",
    "nested/inside.png",
    "sub\\inside.png",
    # Not a traversal, but not an ordinary name either: joined into a path here
    # and printed by `04` when a conversation is skipped for it.
    "chart\n.png",
    "chart\x00.png",
]


@pytest.mark.parametrize("file_name", ESCAPING_NAMES, ids=lambda value: str(value))
def test_a_file_name_cannot_reach_outside_the_attachments_directory(
    attachments_dir: Path, file_name: str
) -> None:
    (attachments_dir.parent / "outside.png").write_bytes(b"x")
    export = one_conversation(message(text="hi", files=[{"file_name": file_name}]))
    item = only(export, settings_for(attachments_dir))
    assert item.attachments[0].klass == "unsupported"
    assert item.attachments[0].source_path is None


def test_a_name_a_posix_filesystem_allows_is_still_accepted() -> None:
    """`:` and `*` are legal where these exports come from; refusing them would
    report a file that is really there as bytes we do not have."""
    assert planning.safe_component("notes: draft *2.png")
    assert not planning.safe_component("notes\rdraft.png")


def test_a_symlink_is_recorded_at_the_target_that_was_checked(
    export_dir: Path, attachments_dir: Path
) -> None:
    """`16` must upload the file `_within` validated, not whatever the link points
    at by then."""
    real = attachments_dir / "store"
    real.mkdir()
    (real / "chart.png").write_bytes(b"x")
    (attachments_dir / "q3-chart.png").symlink_to(real / "chart.png")

    attachments = find(
        plan_of(export_dir, attachments_dir), ATTACHMENT_CONVERSATION
    ).attachments
    upload = next(item for item in attachments if item.file_name == "q3-chart.png")
    assert upload.klass == "upload"
    assert upload.source_path == (real / "chart.png").resolve()


def test_a_symlink_out_of_the_attachments_directory_is_refused(
    export_dir: Path, attachments_dir: Path
) -> None:
    outside = attachments_dir.parent / "chart.png"
    outside.write_bytes(b"x")
    (attachments_dir / "q3-chart.png").symlink_to(outside)

    attachments = find(
        plan_of(export_dir, attachments_dir), ATTACHMENT_CONVERSATION
    ).attachments
    missing = next(item for item in attachments if item.file_name == "q3-chart.png")
    assert missing.klass == "unsupported"
    assert missing.reason == planning.BYTES_NOT_IN_EXPORT


def test_an_attachment_on_a_dropped_branch_is_not_planned(
    export_dir: Path, attachments_dir: Path
) -> None:
    """Only the active path is migrated, so only its files are."""
    plan = plan_of(export_dir, attachments_dir)
    assert all(
        not item.attachments
        for item in plan.conversations
        if item.uuid != ATTACHMENT_CONVERSATION
    )


def test_the_plan_refuses_a_field_it_does_not_know() -> None:
    """`plan.json` is a contract `05`, `12` and `19` read."""
    with pytest.raises(ValueError):
        planning.PlanTotals.model_validate(
            {
                "conversations": 1,
                "messages": 1,
                "attachments": 0,
                "migratable": 1,
                "unsupported": 0,
                "surprise": 1,
            }
        )
