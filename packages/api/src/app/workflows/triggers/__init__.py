"""Trigger adapters: pure payload helpers + thin durable invocations."""

from __future__ import annotations

from app.workflows.triggers.comment_payload import classifyComment, validateCommentPayload
from app.workflows.triggers.invoke import (
    handleIssueCommentCreated,
    handlePullRequestOpened,
)
from app.workflows.triggers.opened_payload import extractOpenedPrPayload
from app.workflows.triggers.types import ReviewTriggerAck

__all__ = [
    "ReviewTriggerAck",
    "classifyComment",
    "extractOpenedPrPayload",
    "handleIssueCommentCreated",
    "handlePullRequestOpened",
    "validateCommentPayload",
]
