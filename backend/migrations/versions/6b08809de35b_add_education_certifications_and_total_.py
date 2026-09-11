"""add education, certifications and total years to job posts

Revision ID: 6b08809de35b
Revises: 7967fbefa544
Create Date: 2026-09-12 04:46:31.306793
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '6b08809de35b'
down_revision: str | None = '7967fbefa544'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("job_posts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("education", sa.String(length=300), nullable=True)
        )
        # server_default is required, not cosmetic: the column is NOT NULL and
        # the table already has rows, which autogenerate cannot know. Without a
        # default the rewrite fails on a NOT NULL violation for every existing
        # job. Kept in place so future inserts that bypass the ORM also work.
        batch_op.add_column(
            sa.Column(
                "certifications",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch_op.add_column(
            sa.Column("total_years_experience", sa.Float(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("job_posts", schema=None) as batch_op:
        batch_op.drop_column("total_years_experience")
        batch_op.drop_column("certifications")
        batch_op.drop_column("education")
