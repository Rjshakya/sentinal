"""Shared helpers for deepagents-based services.

These utilities are provider-agnostic and used by both the review and
setup agents.
"""

from __future__ import annotations


def extract_message_kinds(messages: object) -> tuple[str, ...]:
    """Return ``(type,)`` for each message in a deepagents messages list.

    Tolerant of any non-list input (returns an empty tuple) and of
    messages without a string ``type`` attribute.
    """
    if not isinstance(messages, list):
        return ()
    kinds: list[str] = []
    for message in messages:
        kind = getattr(message, "type", None)
        if isinstance(kind, str):
            kinds.append(kind)
    return tuple(kinds)


__all__: list[str] = ["extract_message_kinds"]
