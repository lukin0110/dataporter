"""The Claude data export, as typed immutable models.

`model.py` holds the types and the active-path rule and performs no I/O.
`source.py` opens a `.zip` or a directory and is the only place that turns a
library exception into an `ExportError`.
"""

from dataporter.export.model import (
    KNOWN_BLOCK_TYPES,
    Attachment,
    ChatMessage,
    ContentBlock,
    Conversation,
    Export,
    ExportModel,
    FileRef,
    TextBlock,
    ThinkingBlock,
    TokenBudgetBlock,
    ToolResultBlock,
    ToolUseBlock,
    UnknownBlock,
    UnsupportedItem,
)
from dataporter.export.source import (
    CONVERSATIONS_FILE,
    KNOWN_FILES,
    OPTIONAL_FILES,
    ExportSource,
    load_export,
    read_export,
)

__all__ = [
    "CONVERSATIONS_FILE",
    "KNOWN_BLOCK_TYPES",
    "KNOWN_FILES",
    "OPTIONAL_FILES",
    "Attachment",
    "ChatMessage",
    "ContentBlock",
    "Conversation",
    "Export",
    "ExportModel",
    "ExportSource",
    "FileRef",
    "TextBlock",
    "ThinkingBlock",
    "TokenBudgetBlock",
    "ToolResultBlock",
    "ToolUseBlock",
    "UnknownBlock",
    "UnsupportedItem",
    "load_export",
    "read_export",
]
