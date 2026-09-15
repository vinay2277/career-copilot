"""screening interviews on postings

Adds the two columns that let a posting screen its applicants, and the link
from an interview session back to the application it belongs to.

Revision ID: d057350767f2
Revises: a464c8587a25
Create Date: 2026-09-16 02:28:26.724723
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d057350767f2"
down_revision: str | None = "a464c8587a25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Named rather than left to the database to pick.
#:
#: Autogenerate rendered `drop_constraint(None, ...)` here, which fails at the
#: moment somebody runs a downgrade — the least convenient moment there is. A
#: migration that can only go forwards is not a migration.
FK_SESSION_APPLICATION = "fk_interview_sessions_application_id"


def upgrade() -> None:
    with op.batch_alter_table("interview_sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("application_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_interview_sessions_application_id"),
            ["application_id"],
            unique=True,
        )
        batch_op.create_foreign_key(
            FK_SESSION_APPLICATION, "posting_applications", ["application_id"], ["id"]
        )

    # server_default is load-bearing, not decoration.
    #
    # These are NOT NULL and the live database already holds postings. Adding
    # the column without a default makes the migration fail on every existing
    # row — which is how a deploy gets rolled back at 2am. The default is kept
    # in the schema rather than dropped afterwards so the same is true of any
    # row inserted by something that predates this code.
    with op.batch_alter_table("job_postings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "interview_required",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "interview_question_count",
                sa.Integer(),
                nullable=False,
                server_default="4",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("job_postings", schema=None) as batch_op:
        batch_op.drop_column("interview_question_count")
        batch_op.drop_column("interview_required")

    with op.batch_alter_table("interview_sessions", schema=None) as batch_op:
        batch_op.drop_constraint(FK_SESSION_APPLICATION, type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_interview_sessions_application_id"))
        batch_op.drop_column("application_id")
