"""extend repos and add sandboxes

Revision ID: 0002_extend_repos_and_sandboxes
Revises: 0001_init
Create Date: 2026-07-04 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_extend_repos_and_sandboxes"
down_revision: Union[str, None] = "0001_init"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Extend the repos table with the new GitHub fields.
    op.add_column(
        "repos",
        sa.Column("name", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "repos",
        sa.Column("html_url", sa.String(length=1024), nullable=True),
    )
    op.add_column(
        "repos",
        sa.Column(
            "private",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "repos",
        sa.Column("default_branch", sa.String(length=255), nullable=True),
    )

    # Backfill `name` from `repo_owner || '/' || repo_name` for any pre-existing rows
    # so the field is non-null in practice going forward. New rows will set it explicitly.
    op.execute(
        sa.text(
            "UPDATE repos SET name = repo_owner || '/' || repo_name WHERE name IS NULL"
        )
    )

    # 2. Create the sandboxes table.
    op.create_table(
        "sandboxes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("repo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sandbox_name", sa.String(length=255), nullable=False),
        sa.Column(
            "state",
            sa.String(length=16),
            server_default="STARTED",
            nullable=False,
        ),
        sa.Column("daytona_sandbox_id", sa.String(length=255), nullable=True),
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
        sa.Column(
            "started_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "stopped_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "state IN ('STARTED', 'PAUSED', 'STOPPED', 'DELETED', 'ARCHIVED')",
            name="ck_sandboxes_state",
        ),
        sa.ForeignKeyConstraint(
            ["repo_id"], ["repos.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sandboxes_user_id", "sandboxes", ["user_id"])
    op.create_index("ix_sandboxes_repo_id", "sandboxes", ["repo_id"])
    op.create_index("ix_sandboxes_state", "sandboxes", ["state"])
    op.create_index(
        "ix_sandboxes_user_repo_state",
        "sandboxes",
        ["user_id", "repo_id", "state"],
    )


def downgrade() -> None:
    op.drop_index("ix_sandboxes_user_repo_state", table_name="sandboxes")
    op.drop_index("ix_sandboxes_state", table_name="sandboxes")
    op.drop_index("ix_sandboxes_repo_id", table_name="sandboxes")
    op.drop_index("ix_sandboxes_user_id", table_name="sandboxes")
    op.drop_table("sandboxes")

    op.drop_column("repos", "default_branch")
    op.drop_column("repos", "private")
    op.drop_column("repos", "html_url")
    op.drop_column("repos", "name")
