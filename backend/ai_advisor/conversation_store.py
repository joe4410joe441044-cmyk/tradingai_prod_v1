"""Bounded, deterministic SQLite persistence for Advisor conversation memory.

D-4 conversation memory is ``CONTEXT_ONLY``.  It is dedicated, server-side,
read-only history for the AI Advisor's own conversational turns.  It is NOT an
authority source and it MUST NOT override canonical specifications, current
runtime source, or validated knowledge.

This module implements ONLY the dedicated conversation storage.  It never
mutates TradingAI runtime state.  All storage writes are classified as
``CONTEXT_PERSISTENCE_ONLY``.

Design rules
------------
- SQLite only, under the existing runtime log data directory (no external DB,
  no Redis, no vector DB, no embeddings, no RAG).
- Provider-neutral: no OpenAI/Ollama/NVIDIA/BytePlus/DeepSeek/Qwen dependency.
- Fail closed: any storage fault raises :class:`AdvisorConversationStoreError`.
- Deterministic ownership/isolation: every operation is scoped to an operator
  identity; a conversation owned by one operator cannot be read or deleted by
  another.
- Bounded: conversation count, per-conversation message count, and per-message
  content length all have explicit conservative limits.
- Sanitized: messages are run through the shared sensitive/path redactor before
  being stored, and no secrets, credentials, tokens, cookies, records of
  environment variables, or operational Python objects are ever persisted.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Optional, Tuple

from pydantic import ConfigDict, Field, field_validator

from backend.ai_advisor.context_builder import sanitize_text
from backend.ai_advisor.conversation_models import (
    AdvisorContractModel,
    AdvisorRole,
    Identifier,
    ShortText,
)

# ---------------------------------------------------------------------------
# Bounds / retention (conservative named constants)
# ---------------------------------------------------------------------------
# Storage bound: number of conversations retained per operator.
MAX_CONVERSATIONS_PER_OPERATOR = 10
# Storage bound: number of messages retained per conversation.
MAX_MESSAGES_PER_CONVERSATION = 40
# Storage bound: maximum content characters for a single persisted message.
MAX_STORED_MESSAGE_CHARACTERS = 8_000
# Prompt bound: maximum conversation-history messages supplied to the Advisor
# (the context envelope caps combined history + current at 20 messages).
MAX_PROMPT_HISTORY_MESSAGES = 19
# Prompt bound: maximum cumulative content characters supplied to the Advisor
# for the recent-history window (leaves headroom under the 40k envelope cap).
MAX_PROMPT_HISTORY_CHARACTERS = 32_000
# Default storage path, following the supervisor audit-store convention.
DEFAULT_CONVERSATION_STORE_PATH = Path("logs/runtime/advisor_conversations.sqlite3")

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,127}$")
_BAD_OPERATORS = (
    "start",
    "stop",
    "enable",
    "disable",
    "submit",
    "cancel",
    "replace",
    "unlock",
    "approve",
    "configure",
    "set_risk",
    "change_mode",
    "create_order",
    "execute",
)


class ConversationMemoryAuthority:
    """Marker: conversation memory mutates only ITS OWN dedicated storage."""

    CARRIES_OPERATIONAL_AUTHORITY = False
    AUTHORITY_CLASSIFICATION = "CONTEXT_PERSISTENCE_ONLY"


class AdvisorConversationStoreErrorCode(str, Enum):
    STORE_UNAVAILABLE = "STORE_UNAVAILABLE"
    CONVERSATION_NOT_FOUND = "CONVERSATION_NOT_FOUND"
    CONVERSATION_FORBIDDEN = "CONVERSATION_FORBIDDEN"
    CONVERSATION_LIMIT_REACHED = "CONVERSATION_LIMIT_REACHED"
    MESSAGE_INVALID = "MESSAGE_INVALID"
    INPUT_INVALID = "INPUT_INVALID"


class AdvisorConversationStoreError(Exception):
    def __init__(self, code: AdvisorConversationStoreErrorCode, safe_message: str):
        super().__init__(safe_message)
        self.code = code
        self.safeMessage = safe_message


class AdvisorConversationStoreContract(AdvisorContractModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        hide_input_in_errors=True,
    )


class AdvisorPersistedMessage(AdvisorConversationStoreContract):
    """A clean, allowlisted persisted message record (never a raw request)."""

    messageId: Identifier
    conversationId: Identifier
    operatorId: Identifier
    role: AdvisorRole
    content: Annotated[
        str,
        Field(min_length=1, max_length=MAX_STORED_MESSAGE_CHARACTERS),
    ]
    createdAt: datetime
    requestId: Optional[Identifier] = None
    responseStatus: Optional[ShortText] = None
    providerModel: Optional[ShortText] = None

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message content must contain visible characters")
        if "\x00" in value:
            raise ValueError("NUL is not allowed")
        allowed = {"\n", "\r", "\t"}
        if any(ord(character) < 32 and character not in allowed for character in value):
            raise ValueError("control characters are not allowed")
        return value

    @field_validator("messageId", "conversationId", "operatorId", "requestId")
    @classmethod
    def validate_identifier(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not value.strip() or not _IDENTIFIER.fullmatch(value):
            raise ValueError("identifier is not a safe logical identifier")
        return value

    @field_validator("responseStatus", "providerModel")
    @classmethod
    def validate_metadata(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not value.strip() or "\x00" in value:
            raise ValueError("metadata must be non-empty safe text")
        allowed = {"\n", "\r", "\t"}
        if any(ord(character) < 32 and character not in allowed for character in value):
            raise ValueError("metadata contains control characters")
        return value.strip()

    @field_validator("createdAt")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("createdAt must be timezone-aware")
        return value.astimezone(timezone.utc)


class AdvisorConversationSummary(AdvisorConversationStoreContract):
    conversationId: Identifier
    createdAt: datetime
    updatedAt: datetime
    messageCount: int

    @field_validator("createdAt", "updatedAt")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(timezone.utc)


def _safe_identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdvisorConversationStoreError(
            AdvisorConversationStoreErrorCode.INPUT_INVALID,
            f"{name} is invalid",
        )
    if not _IDENTIFIER.fullmatch(value):
        raise AdvisorConversationStoreError(
            AdvisorConversationStoreErrorCode.INPUT_INVALID,
            f"{name} is invalid",
        )
    return value


class AdvisorConversationStore:
    """Append-only, bounded, operator-scoped conversation persistence.

    The store is intentionally NOT a general database API.  It exposes only
    the minimal conversation operations and never exposes SQL, filesystem
    paths, or cross-operator queries to callers.
    """

    def __init__(
        self,
        path=DEFAULT_CONVERSATION_STORE_PATH,
        *,
        max_conversations_per_operator: int = MAX_CONVERSATIONS_PER_OPERATOR,
        max_messages_per_conversation: int = MAX_MESSAGES_PER_CONVERSATION,
        max_message_characters: int = MAX_STORED_MESSAGE_CHARACTERS,
    ):
        self.path = Path(path)
        self.max_conversations_per_operator = int(max_conversations_per_operator)
        self.max_messages_per_conversation = int(max_messages_per_conversation)
        self.max_message_characters = int(
            max(max_message_characters, 1)
        )
        self._lock = threading.RLock()
        self._initialize()

    # -- lifecycle ----------------------------------------------------------

    def _connect(self):
        return sqlite3.connect(str(self.path), timeout=5.0, isolation_level=None)

    def _initialize(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "CREATE TABLE IF NOT EXISTS advisor_conversations ("
                    "conversation_id TEXT NOT NULL PRIMARY KEY,"
                    "operator_id TEXT NOT NULL,"
                    "created_at TEXT NOT NULL,"
                    "updated_at TEXT NOT NULL)"
                )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS advisor_conversation_messages ("
                    "seq INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "message_id TEXT NOT NULL UNIQUE,"
                    "conversation_id TEXT NOT NULL,"
                    "operator_id TEXT NOT NULL,"
                    "role TEXT NOT NULL,"
                    "content TEXT NOT NULL,"
                    "created_at TEXT NOT NULL,"
                    "request_id TEXT,"
                    "response_status TEXT,"
                    "provider_model TEXT)"
                )
                db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_conv_msg_conversation "
                    "ON advisor_conversation_messages(conversation_id, operator_id, seq)"
                )
                db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_conv_operator "
                    "ON advisor_conversations(operator_id, updated_at)"
                )
                db.execute("COMMIT")
        except (OSError, sqlite3.Error) as error:
            raise AdvisorConversationStoreError(
                AdvisorConversationStoreErrorCode.STORE_UNAVAILABLE,
                "conversation store unavailable",
            ) from error

    # -- operator scoping ---------------------------------------------------

    def _conversation_owner(self, db, conversation_id: str) -> Optional[str]:
        row = db.execute(
            "SELECT operator_id FROM advisor_conversations WHERE conversation_id=?",
            (conversation_id,),
        ).fetchone()
        return row[0] if row is not None else None

    def owns_conversation(self, operator: str, conversation_id: str) -> bool:
        operator = _safe_identifier(operator, "operator")
        conversation_id = _safe_identifier(conversation_id, "conversationId")
        try:
            with self._connect() as db:
                owner = self._conversation_owner(db, conversation_id)
                return owner == operator
        except sqlite3.Error as error:
            raise AdvisorConversationStoreError(
                AdvisorConversationStoreErrorCode.STORE_UNAVAILABLE,
                "conversation store unavailable",
            ) from error

    def create_conversation(self, operator: str) -> str:
        """Create and return a fresh conversation owned by ``operator``."""
        operator = _safe_identifier(operator, "operator")
        conversation_id = self._new_id("conversation")
        self._ensure_operator_capacity(operator)
        try:
            with self._lock, self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT INTO advisor_conversations"
                    "(conversation_id,operator_id,created_at,updated_at)"
                    " VALUES(?,?,?,?)",
                    (
                        conversation_id,
                        operator,
                        self._now(),
                        self._now(),
                    ),
                )
                db.execute("COMMIT")
        except (sqlite3.Error, OSError) as error:
            raise AdvisorConversationStoreError(
                AdvisorConversationStoreErrorCode.STORE_UNAVAILABLE,
                "conversation store unavailable",
            ) from error
        return conversation_id

    def resolve_conversation(self, operator: str, conversation_id: Optional[str]):
        """Resolve an existing owned conversation or create a fresh one.

        Returns ``(conversation_id, created)``.  If ``conversation_id`` is
        provided but is owned by a different operator, fails closed with
        ``CONVERSATION_FORBIDDEN``.  If it does not exist, it is created for
        ``operator``.
        """
        operator = _safe_identifier(operator, "operator")
        if conversation_id is None or not conversation_id.strip():
            return self.create_conversation(operator), True
        conversation_id = _safe_identifier(conversation_id, "conversationId")
        try:
            with self._connect() as db:
                owner = self._conversation_owner(db, conversation_id)
        except sqlite3.Error as error:
            raise AdvisorConversationStoreError(
                AdvisorConversationStoreErrorCode.STORE_UNAVAILABLE,
                "conversation store unavailable",
            ) from error
        if owner == operator:
            return conversation_id, False
        if owner is not None:
            raise AdvisorConversationStoreError(
                AdvisorConversationStoreErrorCode.CONVERSATION_FORBIDDEN,
                "conversation is not owned by the current operator",
            )
        return self.create_conversation(operator), True

    # -- append / read ------------------------------------------------------

    def append_message(
        self,
        operator: str,
        conversation_id: str,
        message: AdvisorPersistedMessage,
    ) -> None:
        operator = _safe_identifier(operator, "operator")
        conversation_id = _safe_identifier(conversation_id, "conversationId")
        try:
            record = AdvisorPersistedMessage.model_validate(
                message.model_dump(warnings=False)
            )
        except Exception as error:
            raise AdvisorConversationStoreError(
                AdvisorConversationStoreErrorCode.MESSAGE_INVALID,
                "conversation message is invalid",
            ) from error
        if record.conversationId != conversation_id:
            raise AdvisorConversationStoreError(
                AdvisorConversationStoreErrorCode.INPUT_INVALID,
                "conversation id mismatch",
            )
        content = self._sanitize_for_storage(record.content)
        try:
            with self._lock, self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                owner = self._conversation_owner(db, conversation_id)
                if owner != operator:
                    db.execute("ROLLBACK")
                    if owner is None:
                        raise AdvisorConversationStoreError(
                            AdvisorConversationStoreErrorCode.CONVERSATION_NOT_FOUND,
                            "conversation not found",
                        )
                    raise AdvisorConversationStoreError(
                        AdvisorConversationStoreErrorCode.CONVERSATION_FORBIDDEN,
                        "conversation is not owned by the current operator",
                    )
                db.execute(
                    "INSERT INTO advisor_conversation_messages"
                    "(message_id,conversation_id,operator_id,role,content,"
                    "created_at,request_id,response_status,provider_model)"
                    " VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        record.messageId,
                        conversation_id,
                        operator,
                        record.role.value,
                        content,
                        record.createdAt.isoformat(),
                        record.requestId,
                        record.responseStatus,
                        record.providerModel,
                    ),
                )
                db.execute(
                    "UPDATE advisor_conversations SET updated_at=? "
                    "WHERE conversation_id=?",
                    (self._now(), conversation_id),
                )
                self._trim_messages(db, conversation_id)
                db.execute("COMMIT")
        except AdvisorConversationStoreError:
            raise
        except (sqlite3.Error, OSError) as error:
            raise AdvisorConversationStoreError(
                AdvisorConversationStoreErrorCode.STORE_UNAVAILABLE,
                "conversation store unavailable",
            ) from error

    def read_messages(
        self,
        operator: str,
        conversation_id: str,
    ) -> Tuple[AdvisorPersistedMessage, ...]:
        operator = _safe_identifier(operator, "operator")
        conversation_id = _safe_identifier(conversation_id, "conversationId")
        try:
            with self._connect() as db:
                owner = self._conversation_owner(db, conversation_id)
                if owner != operator:
                    raise AdvisorConversationStoreError(
                        AdvisorConversationStoreErrorCode.CONVERSATION_NOT_FOUND,
                        "conversation not found",
                    )
                rows = db.execute(
                    "SELECT message_id,conversation_id,operator_id,role,content,"
                    "created_at,request_id,response_status,provider_model "
                    "FROM advisor_conversation_messages "
                    "WHERE conversation_id=? AND operator_id=? ORDER BY seq",
                    (conversation_id, operator),
                ).fetchall()
            return tuple(
                AdvisorPersistedMessage(
                    messageId=row[0],
                    conversationId=row[1],
                    operatorId=row[2],
                    role=AdvisorRole(row[3]),
                    content=row[4],
                    createdAt=datetime.fromisoformat(row[5]),
                    requestId=row[6],
                    responseStatus=row[7],
                    providerModel=row[8],
                )
                for row in rows
            )
        except AdvisorConversationStoreError:
            raise
        except (sqlite3.Error, OSError, ValueError) as error:
            raise AdvisorConversationStoreError(
                AdvisorConversationStoreErrorCode.STORE_UNAVAILABLE,
                "conversation store unavailable",
            ) from error

    def list_conversations(self, operator: str) -> Tuple[AdvisorConversationSummary, ...]:
        operator = _safe_identifier(operator, "operator")
        try:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT c.conversation_id,c.created_at,c.updated_at,"
                    "COUNT(m.seq) FROM advisor_conversations c "
                    "LEFT JOIN advisor_conversation_messages m "
                    "ON m.conversation_id=c.conversation_id AND m.operator_id=c.operator_id "
                    "WHERE c.operator_id=? GROUP BY c.conversation_id "
                    "ORDER BY c.updated_at DESC",
                    (operator,),
                ).fetchall()
            return tuple(
                AdvisorConversationSummary(
                    conversationId=row[0],
                    createdAt=datetime.fromisoformat(row[1]),
                    updatedAt=datetime.fromisoformat(row[2]),
                    messageCount=int(row[3] or 0),
                )
                for row in rows
            )
        except (sqlite3.Error, OSError, ValueError) as error:
            raise AdvisorConversationStoreError(
                AdvisorConversationStoreErrorCode.STORE_UNAVAILABLE,
                "conversation store unavailable",
            ) from error

    def delete_conversation(self, operator: str, conversation_id: str) -> bool:
        """Delete an operator-owned conversation and its messages.

        Returns ``True`` when a conversation was removed.  A conversation
        owned by another operator is treated as not found (no cross-operator
        destructive access).
        """
        operator = _safe_identifier(operator, "operator")
        conversation_id = _safe_identifier(conversation_id, "conversationId")
        try:
            with self._lock, self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                deleted = db.execute(
                    "DELETE FROM advisor_conversations "
                    "WHERE conversation_id=? AND operator_id=?",
                    (conversation_id, operator),
                ).rowcount
                if deleted:
                    db.execute(
                        "DELETE FROM advisor_conversation_messages "
                        "WHERE conversation_id=? AND operator_id=?",
                        (conversation_id, operator),
                    )
                db.execute("COMMIT")
                return bool(deleted)
        except (sqlite3.Error, OSError) as error:
            raise AdvisorConversationStoreError(
                AdvisorConversationStoreErrorCode.STORE_UNAVAILABLE,
                "conversation store unavailable",
            ) from error

    def delete_message(
        self,
        operator: str,
        conversation_id: str,
        message_id: str,
    ) -> bool:
        """Remove one operator-scoped message (used to roll back a failed turn)."""
        operator = _safe_identifier(operator, "operator")
        conversation_id = _safe_identifier(conversation_id, "conversationId")
        message_id = _safe_identifier(message_id, "messageId")
        try:
            with self._lock, self._connect() as db:
                db.execute("BEGIN IMMEDIATE")
                deleted = db.execute(
                    "DELETE FROM advisor_conversation_messages "
                    "WHERE message_id=? AND conversation_id=? AND operator_id=?",
                    (message_id, conversation_id, operator),
                ).rowcount
                db.execute("COMMIT")
                return bool(deleted)
        except (sqlite3.Error, OSError) as error:
            raise AdvisorConversationStoreError(
                AdvisorConversationStoreErrorCode.STORE_UNAVAILABLE,
                "conversation store unavailable",
            ) from error

    # -- prompt window helper ----------------------------------------------

    def bounded_history(
        self,
        records: Tuple[AdvisorPersistedMessage, ...],
        *,
        max_messages: int = MAX_PROMPT_HISTORY_MESSAGES,
        max_characters: int = MAX_PROMPT_HISTORY_CHARACTERS,
    ) -> Tuple[AdvisorPersistedMessage, ...]:
        """Return the newest bounded, chronological recent-history window.

        Both the message count and cumulative content budget are enforced so
        the history passed to the Advisor is guaranteed bounded and never the
        full stored database.  Ordering is preserved (oldest-to-newest of the
        selected window).
        """
        budget = int(max_characters)
        selected = []
        for record in reversed(records):
            budget -= len(record.content)
            if budget < 0 or len(selected) >= max_messages:
                break
            selected.append(record)
        selected.reverse()
        return tuple(selected)

    # -- helpers ------------------------------------------------------------

    def _trim_messages(self, db, conversation_id: str) -> None:
        rows = db.execute(
            "SELECT seq FROM advisor_conversation_messages "
            "WHERE conversation_id=? ORDER BY seq DESC",
            (conversation_id,),
        ).fetchall()
        keep = self.max_messages_per_conversation
        if len(rows) > keep:
            discard = [row[0] for row in rows[keep:]]
            for seq in discard:
                db.execute(
                    "DELETE FROM advisor_conversation_messages WHERE seq=?",
                    (seq,),
                )

    def _ensure_operator_capacity(self, operator: str) -> None:
        try:
            with self._lock, self._connect() as db:
                count = db.execute(
                    "SELECT COUNT(*) FROM advisor_conversations WHERE operator_id=?",
                    (operator,),
                ).fetchone()[0]
                if count >= self.max_conversations_per_operator:
                    rows = db.execute(
                        "SELECT conversation_id FROM advisor_conversations "
                        "WHERE operator_id=? ORDER BY updated_at ASC",
                        (operator,),
                    ).fetchall()
                    if rows:
                        oldest = rows[0][0]
                        db.execute(
                            "DELETE FROM advisor_conversations "
                            "WHERE conversation_id=? AND operator_id=?",
                            (oldest, operator),
                        )
                        db.execute(
                            "DELETE FROM advisor_conversation_messages "
                            "WHERE conversation_id=? AND operator_id=?",
                            (oldest, operator),
                        )
        except (sqlite3.Error, OSError) as error:
            raise AdvisorConversationStoreError(
                AdvisorConversationStoreErrorCode.STORE_UNAVAILABLE,
                "conversation store unavailable",
            ) from error

    def _sanitize_for_storage(self, content: str) -> str:
        cleaned = sanitize_text(content)
        value = cleaned.value.strip()
        if not value:
            raise AdvisorConversationStoreError(
                AdvisorConversationStoreErrorCode.MESSAGE_INVALID,
                "conversation message content is empty after sanitization",
            )
        if len(value) > self.max_message_characters:
            raise AdvisorConversationStoreError(
                AdvisorConversationStoreErrorCode.MESSAGE_INVALID,
                "conversation message content exceeds limit",
            )
        return value

    @staticmethod
    def _new_id(prefix: str) -> str:
        import secrets

        return f"{prefix}-{secrets.token_hex(16)}"

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
