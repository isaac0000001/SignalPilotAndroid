from alembic import op
import sqlalchemy as sa


revision = "0001_add_scan_runs"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scan_runs",

        sa.Column(
            "id",
            sa.Uuid(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),

        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
        ),

        sa.Column(
            "mode",
            sa.String(30),
            nullable=False,
        ),

        sa.Column(
            "symbols",
            sa.JSON(),
            nullable=False,
        ),

        sa.Column(
            "timeframes",
            sa.JSON(),
            nullable=False,
        ),

        sa.Column(
            "account_balance",
            sa.Numeric(20, 8),
            nullable=False,
        ),

        sa.Column(
            "risk_percent",
            sa.Numeric(8, 4),
            nullable=False,
        ),

        sa.Column(
            "risk_reward_ratio",
            sa.Numeric(8, 4),
            nullable=False,
        ),

        sa.Column(
            "minimum_score",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "markets_requested",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "markets_analyzed",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "opportunities_found",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "markets_failed",
            sa.Integer(),
            nullable=False,
        ),

        sa.Column(
            "results",
            sa.JSON(),
            nullable=False,
        ),

        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
        ),

        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),

        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_scan_runs_started_at",
        "scan_runs",
        ["started_at"],
    )

    op.create_index(
        "ix_scan_runs_status",
        "scan_runs",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scan_runs_status",
        table_name="scan_runs",
    )

    op.drop_index(
        "ix_scan_runs_started_at",
        table_name="scan_runs",
    )

    op.drop_table("scan_runs")
