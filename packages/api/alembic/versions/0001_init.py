"""init review domain tables

Revision ID: 0001_init
Revises:
Create Date: 2026-06-30 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_init"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "repos",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("org_id", sa.String(length=128), nullable=True),
        sa.Column("github_repo_id", sa.BigInteger(), nullable=False),
        sa.Column("repo_name", sa.String(length=255), nullable=False),
        sa.Column("repo_owner", sa.String(length=255), nullable=False),
        sa.Column("clone_url", sa.String(length=1024), nullable=False),
        sa.Column("github_installation_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("github_repo_id", name="uq_repos_github_repo_id"),
        sa.UniqueConstraint("repo_owner", "repo_name", name="uq_repos_owner_name"),
    )
    op.create_index("ix_repos_user_id", "repos", ["user_id"])
    op.create_index("ix_repos_org_id", "repos", ["org_id"])

    op.create_table(
        "pull_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("repo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("github_pr_id", sa.BigInteger(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("author", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="OPEN", nullable=False),
        sa.Column("base_branch", sa.String(length=255), nullable=False),
        sa.Column("base_sha", sa.String(length=64), nullable=False),
        sa.Column("head_branch", sa.String(length=255), nullable=False),
        sa.Column("head_sha", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'CLOSED', 'MERGED')",
            name="ck_pull_requests_status",
        ),
        sa.ForeignKeyConstraint(
            ["repo_id"], ["repos.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("github_pr_id", name="uq_pull_requests_github_pr_id"),
        sa.UniqueConstraint("repo_id", "number", name="uq_pull_requests_repo_id_number"),
    )
    op.create_index("ix_pull_requests_repo_id", "pull_requests", ["repo_id"])
    op.create_index("ix_pull_requests_status", "pull_requests", ["status"])

    op.create_table(
        "commit_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("pr_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sha", sa.String(length=64), nullable=False),
        sa.Column("previous_reviewed_sha", sa.String(length=64), nullable=True),
        sa.Column("analysis_status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "analysis_status IN ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED')",
            name="ck_commit_snapshots_analysis_status",
        ),
        sa.ForeignKeyConstraint(
            ["pr_id"], ["pull_requests.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pr_id", "sha", name="uq_commit_snapshots_pr_id_sha"),
    )
    op.create_index("ix_commit_snapshots_pr_id", "commit_snapshots", ["pr_id"])

    op.create_table(
        "code_comments",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("pr_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("commit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("github_comment_id", sa.BigInteger(), nullable=True),
        sa.Column("file_name", sa.String(length=1024), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("from_line", sa.Integer(), nullable=False),
        sa.Column("to_line", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(length=8), server_default="RIGHT", nullable=False),
        sa.Column("node_type", sa.String(length=128), nullable=True),
        sa.Column("state", sa.String(length=16), server_default="ACTIVE", nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severity IN ('P1_CRITICAL', 'P2_WARNING', 'P3_NITPICK')",
            name="ck_code_comments_severity",
        ),
        sa.CheckConstraint(
            "side IN ('RIGHT', 'LEFT')", name="ck_code_comments_side"
        ),
        sa.CheckConstraint(
            "state IN ('ACTIVE', 'OUTDATED', 'RESOLVED')",
            name="ck_code_comments_state",
        ),
        sa.ForeignKeyConstraint(
            ["pr_id"], ["pull_requests.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["commit_id"], ["commit_snapshots.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_code_comments_pr_id", "code_comments", ["pr_id"])
    op.create_index("ix_code_comments_commit_id", "code_comments", ["commit_id"])
    op.create_index(
        "ix_code_comments_commit_file_state",
        "code_comments",
        ["commit_id", "file_name", "state"],
    )

    op.create_table(
        "review_summaries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("pr_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("commit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("github_review_id", sa.BigInteger(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("verdict", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "verdict IN ('APPROVE', 'COMMENT', 'REQUEST_CHANGES')",
            name="ck_review_summaries_verdict",
        ),
        sa.ForeignKeyConstraint(
            ["pr_id"], ["pull_requests.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["commit_id"], ["commit_snapshots.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("commit_id", name="uq_review_summaries_commit_id"),
    )
    op.create_index("ix_review_summaries_pr_id", "review_summaries", ["pr_id"])


def downgrade() -> None:
    op.drop_index("ix_review_summaries_pr_id", table_name="review_summaries")
    op.drop_table("review_summaries")

    op.drop_index("ix_code_comments_commit_file_state", table_name="code_comments")
    op.drop_index("ix_code_comments_commit_id", table_name="code_comments")
    op.drop_index("ix_code_comments_pr_id", table_name="code_comments")
    op.drop_table("code_comments")

    op.drop_index("ix_commit_snapshots_pr_id", table_name="commit_snapshots")
    op.drop_table("commit_snapshots")

    op.drop_index("ix_pull_requests_status", table_name="pull_requests")
    op.drop_index("ix_pull_requests_repo_id", table_name="pull_requests")
    op.drop_table("pull_requests")

    op.drop_index("ix_repos_org_id", table_name="repos")
    op.drop_index("ix_repos_user_id", table_name="repos")
    op.drop_table("repos")
