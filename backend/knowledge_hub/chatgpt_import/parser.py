"""Parser for the official ChatGPT export document.

The parser preserves conversation, message, parent, and branch identity.
An unknown timestamp stays ``UNKNOWN``. The import time is never written into
a conversation or message timestamp field.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from .account import AccountError, resolve_account
from .models import (
    Conversation,
    ImportLimits,
    Message,
    ParseResult,
    STATUS_ERROR,
    STATUS_OK,
)
from .zip_security import read_conversations_json


_FORMAT_LIST = "CHATGPT_CONVERSATIONS_JSON_ARRAY"
_FORMAT_OBJECT = "CHATGPT_CONVERSATIONS_JSON_OBJECT"
_FORMAT_SINGLE = "CHATGPT_SINGLE_CONVERSATION_OBJECT"
_FORMAT_UNKNOWN = "UNKNOWN"
_UNKNOWN = "UNKNOWN"


def parse_export(
    source: str | Path | bytes,
    account_alias: str,
    limits: ImportLimits | None = None,
) -> ParseResult:
    bounds = limits or ImportLimits()
    try:
        account = resolve_account(account_alias)
    except AccountError as exc:
        return ParseResult(STATUS_ERROR, _FORMAT_UNKNOWN, None, error=exc.code)
    payload = read_conversations_json(source, bounds)
    if payload.error is not None or payload.data is None:
        return ParseResult(STATUS_ERROR, _FORMAT_UNKNOWN, None, error=payload.error or "INVALID_ZIP")
    try:
        document = json.loads(payload.data.decode("utf-8"))
    except UnicodeDecodeError:
        return ParseResult(STATUS_ERROR, _FORMAT_UNKNOWN, None, error="INVALID_ENCODING")
    except (json.JSONDecodeError, ValueError):
        return ParseResult(STATUS_ERROR, _FORMAT_UNKNOWN, None, error="INVALID_JSON")
    conversations, export_format = _select_conversations(document)
    if conversations is None:
        return ParseResult(STATUS_ERROR, _FORMAT_UNKNOWN, None, error="UNSUPPORTED_FORMAT")
    if len(conversations) > bounds.max_conversations:
        return ParseResult(STATUS_ERROR, export_format, None, error="CONVERSATION_LIMIT")
    source_export_id = hashlib.sha256(payload.data).hexdigest()
    parsed: list[Conversation] = []
    total_messages = 0
    for raw in conversations:
        if not isinstance(raw, dict):
            return ParseResult(STATUS_ERROR, export_format, source_export_id, error="UNSUPPORTED_FORMAT")
        try:
            conversation = _parse_conversation(raw, account.alias, source_export_id, bounds)
        except _ParseFailure as exc:
            return ParseResult(STATUS_ERROR, export_format, source_export_id, error=exc.code)
        total_messages += len(conversation.messages)
        if total_messages > bounds.max_messages:
            return ParseResult(STATUS_ERROR, export_format, source_export_id, error="MESSAGE_LIMIT")
        parsed.append(conversation)
    return ParseResult(STATUS_OK, export_format, source_export_id, tuple(parsed))


class _ParseFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _select_conversations(document: Any) -> tuple[list[Any] | None, str]:
    if isinstance(document, list):
        return document, _FORMAT_LIST
    if isinstance(document, dict):
        listed = document.get("conversations")
        if isinstance(listed, list):
            return listed, _FORMAT_OBJECT
        if "mapping" in document or "messages" in document:
            return [document], _FORMAT_SINGLE
    return None, _FORMAT_UNKNOWN


def _timestamp(value: Any) -> str:
    if isinstance(value, bool):
        return _UNKNOWN
    if isinstance(value, (int, float)):
        if value <= 0:
            return _UNKNOWN
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return _UNKNOWN
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return _UNKNOWN
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return _UNKNOWN
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        try:
            return moment.astimezone(timezone.utc).isoformat()
        except (OverflowError, ValueError):
            return _UNKNOWN
    return _UNKNOWN


def _content(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    raw = message.get("content")
    if isinstance(raw, str):
        return raw
    if not isinstance(raw, dict):
        return ""
    text = raw.get("text")
    if isinstance(text, str) and text.strip():
        return text
    parts = raw.get("parts")
    if isinstance(parts, list):
        pieces = [part for part in parts if isinstance(part, str)]
        return "\n".join(pieces)
    return ""


def _role(message: Any) -> str:
    if not isinstance(message, dict):
        return _UNKNOWN
    author = message.get("author")
    if isinstance(author, dict):
        role = author.get("role")
        if isinstance(role, str) and role.strip():
            return role.strip()
    role = message.get("role")
    if isinstance(role, str) and role.strip():
        return role.strip()
    return _UNKNOWN


def _nodes(conversation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping = conversation.get("mapping")
    if isinstance(mapping, dict):
        nodes: dict[str, dict[str, Any]] = {}
        for key, entry in mapping.items():
            if not isinstance(key, str) or not isinstance(entry, dict):
                raise _ParseFailure("UNSUPPORTED_FORMAT")
            nodes[key] = entry
        return nodes
    messages = conversation.get("messages")
    if isinstance(messages, list):
        nodes = {}
        for entry in messages:
            if not isinstance(entry, dict):
                raise _ParseFailure("UNSUPPORTED_FORMAT")
            node_id = entry.get("id")
            if not isinstance(node_id, str) or node_id == "":
                raise _ParseFailure("UNSUPPORTED_FORMAT")
            nodes[node_id] = {
                "message": entry,
                "parent": entry.get("parent"),
                "children": entry.get("children"),
            }
        return nodes
    raise _ParseFailure("UNSUPPORTED_FORMAT")


def _branch_identity(node_id: str, nodes: dict[str, dict[str, Any]]) -> str:
    branch = "MAIN"
    current = node_id
    visited: set[str] = set()
    while current and current not in visited:
        visited.add(current)
        entry = nodes.get(current)
        if not isinstance(entry, dict):
            break
        parent = entry.get("parent")
        if not isinstance(parent, str) or parent == "":
            break
        parent_entry = nodes.get(parent)
        children = parent_entry.get("children") if isinstance(parent_entry, dict) else None
        if isinstance(children, list) and len(children) > 1:
            branch = current
        current = parent
    return branch


def _parent(node_id: str, nodes: dict[str, dict[str, Any]]) -> str | None:
    entry = nodes.get(node_id)
    if not isinstance(entry, dict):
        return None
    parent = entry.get("parent")
    if isinstance(parent, str) and parent != "":
        return parent
    return None


def _parse_conversation(
    raw: dict[str, Any],
    account_alias: str,
    source_export_id: str,
    limits: ImportLimits,
) -> Conversation:
    conversation_id = raw.get("id")
    if not isinstance(conversation_id, str) or conversation_id.strip() == "":
        raise _ParseFailure("UNSUPPORTED_FORMAT")
    title = raw.get("title")
    if not isinstance(title, str) or title.strip() == "":
        title = "UNTITLED"
    created = _timestamp(raw.get("create_time"))
    updated = _timestamp(raw.get("update_time"))
    nodes = _nodes(raw)
    messages: list[Message] = []
    for node_id, entry in nodes.items():
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        text = _content(message)
        if text.strip() == "":
            continue
        if len(text.encode("utf-8")) > limits.max_message_bytes:
            raise _ParseFailure("MESSAGE_TOO_LARGE")
        message_id = message.get("id")
        if not isinstance(message_id, str) or message_id.strip() == "":
            message_id = node_id
        messages.append(
            Message(
                account_alias=account_alias,
                conversation_id=conversation_id,
                conversation_title=title,
                conversation_created_at=created,
                conversation_updated_at=updated,
                message_id=message_id,
                role=_role(message),
                message_created_at=_timestamp(message.get("create_time")),
                parent_message_id=_parent(node_id, nodes),
                branch_identity=_branch_identity(node_id, nodes),
                content=text,
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                source_export_id=source_export_id,
            )
        )
    return Conversation(
        conversation_id=conversation_id,
        title=title,
        created_at=created,
        updated_at=updated,
        messages=tuple(messages),
    )
