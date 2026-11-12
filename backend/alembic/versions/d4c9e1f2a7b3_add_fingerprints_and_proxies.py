"""add browser fingerprints and proxy endpoints

Revision ID: d4c9e1f2a7b3
Revises: 60cd5c95fde1
Create Date: 2026-05-04 10:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4c9e1f2a7b3'
down_revision: Union[str, None] = '60cd5c95fde1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'browser_fingerprints',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('target', sa.String(length=16), nullable=False),
        sa.Column('seed', sa.Integer(), nullable=False),
        sa.Column('schema_version', sa.Integer(), nullable=False),
        sa.Column('summary_json', sa.Text(), nullable=False),
        sa.Column('profile_json', sa.Text(), nullable=False),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('browser_fingerprints', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_browser_fingerprints_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_browser_fingerprints_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_browser_fingerprints_target'), ['target'], unique=False)

    op.create_table(
        'proxy_endpoints',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('protocol', sa.String(length=16), nullable=False),
        sa.Column('host', sa.String(length=255), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(length=128), nullable=False),
        sa.Column('password_encrypted', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('status_message', sa.Text(), nullable=False),
        sa.Column('exit_ip', sa.String(length=64), nullable=False),
        sa.Column('exit_country', sa.String(length=64), nullable=False),
        sa.Column('exit_region', sa.String(length=64), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('last_checked_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('proxy_endpoints', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_proxy_endpoints_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_proxy_endpoints_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_proxy_endpoints_status'), ['status'], unique=False)

    with op.batch_alter_table('platform_accounts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('fingerprint_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('proxy_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_platform_accounts_fingerprint_id'), ['fingerprint_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_platform_accounts_proxy_id'), ['proxy_id'], unique=False)
        batch_op.create_foreign_key('fk_platform_accounts_fingerprint_id', 'browser_fingerprints', ['fingerprint_id'], ['id'])
        batch_op.create_foreign_key('fk_platform_accounts_proxy_id', 'proxy_endpoints', ['proxy_id'], ['id'])


def downgrade() -> None:
    with op.batch_alter_table('platform_accounts', schema=None) as batch_op:
        batch_op.drop_constraint('fk_platform_accounts_proxy_id', type_='foreignkey')
        batch_op.drop_constraint('fk_platform_accounts_fingerprint_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_platform_accounts_proxy_id'))
        batch_op.drop_index(batch_op.f('ix_platform_accounts_fingerprint_id'))
        batch_op.drop_column('proxy_id')
        batch_op.drop_column('fingerprint_id')

    with op.batch_alter_table('proxy_endpoints', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_proxy_endpoints_status'))
        batch_op.drop_index(batch_op.f('ix_proxy_endpoints_user_id'))
        batch_op.drop_index(batch_op.f('ix_proxy_endpoints_id'))

    op.drop_table('proxy_endpoints')

    with op.batch_alter_table('browser_fingerprints', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_browser_fingerprints_target'))
        batch_op.drop_index(batch_op.f('ix_browser_fingerprints_user_id'))
        batch_op.drop_index(batch_op.f('ix_browser_fingerprints_id'))

    op.drop_table('browser_fingerprints')
