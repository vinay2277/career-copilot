"""interviews required by default

Flips the column default, and brings existing postings with it.

The default alone would only affect roles posted from now on, leaving every
role already on the board silently exempt — a student applying to one would see
no interview and have no way to know why, which is exactly the confusion this
change exists to remove.

Revision ID: b9b062dad67d
Revises: 00c33acbf6a0
Create Date: 2026-09-16 04:02:11.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9b062dad67d"
down_revision: str | None = "00c33acbf6a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Only open and draft roles. A closed role is history: switching a round on
    # for it would put an Interview button in front of somebody whose
    # application is already decided.
    op.execute(
        sa.text(
            "UPDATE job_postings SET interview_required = true "
            "WHERE status IN ('draft', 'open')"
        )
    )

    with op.batch_alter_table("job_postings", schema=None) as batch_op:
        batch_op.alter_column(
            "interview_required",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.true(),
        )


def downgrade() -> None:
    # The data change is not reversed. Which postings had interviews switched
    # on before this ran is not recorded anywhere, so "undoing" it would mean
    # guessing — and guessing wrong turns somebody's live role off.
    with op.batch_alter_table("job_postings", schema=None) as batch_op:
        batch_op.alter_column(
            "interview_required",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.false(),
        )
