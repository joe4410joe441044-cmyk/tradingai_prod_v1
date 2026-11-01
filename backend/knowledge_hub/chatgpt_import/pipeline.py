"""Shared classification pipeline for preview and import."""

from __future__ import annotations

from .filters import classify_text, inspect_privacy
from .models import Conversation, Evaluation


def evaluate_conversation(conversation: Conversation) -> tuple[Evaluation, ...]:
    results: list[Evaluation] = []
    for message in conversation.messages:
        relevance = classify_text(message.content, conversation_title=conversation.title)
        privacy = inspect_privacy(message.content, conversation.title)
        results.append(
            Evaluation(
                conversation=conversation,
                message=message,
                relevance=relevance,
                privacy=privacy,
            )
        )
    return tuple(results)


def evaluate_conversations(conversations: tuple[Conversation, ...]) -> tuple[Evaluation, ...]:
    results: list[Evaluation] = []
    for conversation in conversations:
        results.extend(evaluate_conversation(conversation))
    return tuple(results)


def importable(evaluations: tuple[Evaluation, ...]) -> tuple[Evaluation, ...]:
    return tuple(item for item in evaluations if item.importable)
