### packages/api/src/app/models/review.py

```diff

deleted file mode 100644
index 75422ee..0000000
--- a/packages/api/src/app/models/review.py
+++ /dev/null
@@ -1,110 +0,0 @@
    2       -"""``review`` table — durable per-run record of one review workflow run.
    3       -
    4       -One row per DBOS invocation of ``review_workflow``, keyed by the
    5       -deterministic workflow id (``review:{repo_id}:{pr_number}:{head_sha[:7]}``).
    6       -Mirrors the workflow lifecycle so the dashboard and analytics can query
    7       -review runs — including failures, which currently leave no record beyond
    8       -DBOS's own workflow table — without depending on DBOS state.
    9       -
   10       -State machine: ``STARTING`` → ``RUNNING`` → (``SUCCESS`` | ``FAILED``).
   11       -Every transition is best-effort: a DB blip never breaks the workflow
   12       -itself. The DBOS workflow's own state is the source of truth; this table
   13       -is the user-facing mirror.
   14       -
   15       -The LLM columns snapshot the resolved
   16       -:class:`app.core.llm.LLMConfig` at run time so failed runs keep their
   17       -LLM identity even though no usage/summary rows exist. ``error_context``
   18       -carries the JSON payload of :class:`app.services.review.errors.ReviewAgentsInvocationError`
   19       -(failed/succeeded agent names, retryable flags, cause) when it was the
   20       -failure source.
   21       -"""
   22       -
   23       -from __future__ import annotations
   24       -
   25       -import enum
   26       -from datetime import UTC, datetime
   27       -
   28       -from sqlalchemy import Column, String, text
   29       -from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
   30       -from sqlmodel import Field, ForeignKey, SQLModel
   31       -
   32       -from app.utils.util import uuidToStr
   33       -
   34       -
   35       -class ReviewState(str, enum.Enum):
   36       -    """Lifecycle state of a :class:`Review` row.
   37       -
   38       -    Stored as a ``String(16)`` column (the ``IndexRun`` pattern) to
   39       -    avoid PG-ENUM ALTER churn.
   40       -    """
   41       -
   42       -    STARTING = "STARTING"
   43       -    RUNNING = "RUNNING"
   44       -    SUCCESS = "SUCCESS"
   45       -    FAILED = "FAILED"
   46       -
   47       -
   48       -class Review(SQLModel, table=True):
   49       -    id: str = Field(default_factory=uuidToStr, primary_key=True)
   50       -
   51       -    user_id: str = Field(nullable=False, index=True)
   52       -    repo_id: str = Field(
   53       -        sa_column_args=(ForeignKey("repo.id", ondelete="CASCADE"),),
   54       -        nullable=False,
   55       -        index=True,
   56       -    )
   57       -    gh_repo_id: int = Field(nullable=False)
   58       -    pr_id: str = Field(
   59       -        sa_column_args=(ForeignKey("pullrequest.id", ondelete="CASCADE"),),
   60       -        nullable=False,
   61       -        index=True,
   62       -    )
   63       -    pr_number: int = Field(nullable=False)
   64       -    commit_id: str = Field(nullable=False, index=True)
   65       -    base_sha: str | None = Field(default=None)
   66       -
   67       -    workflow_id: str = Field(nullable=False, unique=True, index=True)
   68       -    trigger: str | None = Field(default=None)
   69       -
   70       -    state: ReviewState = Field(
   71       -        default=ReviewState.STARTING,
   72       -        sa_column=Column(String(16), nullable=False, index=True),
   73       -    )
   74       -    comment_count: int | None = Field(default=None)
   75       -    github_review_id: str | None = Field(default=None)
   76       -
   77       -    error_name: str | None = Field(default=None)
   78       -    error_message: str | None = Field(default=None)
   79       -    error_context: dict | None = Field(
   80       -        default=None,
   81       -        sa_column=Column(JSONB, nullable=True),
   82       -    )
   83       -
   84       -    sandbox_id: str | None = Field(default=None)
   85       -    llm_provider: str | None = Field(default=None)
   86       -    llm_model: str | None = Field(default=None)
   87       -    llm_base_url: str | None = Field(default=None)
   88       -
   89       -    started_at: datetime | None = Field(
   90       -        default=None,
   91       -        sa_column=Column(TIMESTAMP(timezone=True), nullable=True),
   92       -    )
   93       -    completed_at: datetime | None = Field(
   94       -        default=None,
   95       -        sa_column=Column(TIMESTAMP(timezone=True), nullable=True),
   96       -    )
   97       -    created_at: datetime = Field(
   98       -        default_factory=lambda: datetime.now(UTC),
   99       -        sa_column=Column(
  100       -            TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
  101       -        ),
  102       -    )
  103       -    updated_at: datetime = Field(
  104       -        default_factory=lambda: datetime.now(UTC),
  105       -        sa_column=Column(
  106       -            TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")
  107       -        ),
  108       -    )
  109       -
  110       -
  111       -__all__ = ["Review", "ReviewState"]
\ No newline at end of file

```
