"""Create RBAC and audit log tables.

Revision ID: compliance_rbac_audit
Revises: 24025de78a2d
Create Date: 2026-04-04 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'compliance_rbac_audit'
down_revision = '24025de78a2d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create RBAC and audit log tables."""
    
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('username', sa.String(255), nullable=False),
        sa.Column('password_hash', sa.String(256), nullable=True),
        sa.Column('full_name', sa.String(255), nullable=True),
        sa.Column('avatar_url', sa.String(512), nullable=True),
        sa.Column('bio', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('is_verified', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('oauth_provider', sa.String(64), nullable=True),
        sa.Column('oauth_id', sa.String(256), nullable=True),
        sa.Column('mfa_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('mfa_secret', sa.String(256), nullable=True),
        sa.Column('password_changed_at', sa.String(32), nullable=True),
        sa.Column('password_expires_at', sa.String(32), nullable=True),
        sa.Column('last_login_at', sa.String(32), nullable=True),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email', name='uc_email'),
        sa.UniqueConstraint('username', name='uc_username'),
        sa.UniqueConstraint('oauth_provider', 'oauth_id', name='uc_oauth_provider_id'),
    )
    op.create_index('ix_users_email', 'users', ['email'])
    op.create_index('ix_users_is_active', 'users', ['is_active'])
    
    # Create roles table
    op.create_table(
        'roles',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('is_builtin', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uc_role_name'),
    )
    op.create_index('ix_roles_name', 'roles', ['name'])
    op.create_index('ix_roles_is_builtin', 'roles', ['is_builtin'])
    
    # Create permissions table
    op.create_table(
        'permissions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('resource', sa.String(64), nullable=False),
        sa.Column('action', sa.String(64), nullable=False),
        sa.Column('scope', sa.Enum('global', 'project', 'resource', name='permission_scope'), nullable=False),
        sa.Column('resource_id_pattern', sa.String(255), nullable=True),
        sa.Column('allowed_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('restricted_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='[]'),
        sa.Column('is_builtin', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uc_permission_name'),
    )
    op.create_index('ix_permissions_name', 'permissions', ['name'])
    op.create_index('ix_permissions_resource_action', 'permissions', ['resource', 'action'])
    
    # Create user_roles association table
    op.create_table(
        'user_roles',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'role_id'),
    )
    
    # Create role_permissions association table
    op.create_table(
        'role_permissions',
        sa.Column('role_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('permission_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['roles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('role_id', 'permission_id'),
    )
    
    # Create user_permissions association table
    op.create_table(
        'user_permissions',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('permission_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'permission_id'),
    )
    
    # Create audit_logs table
    op.create_table(
        'audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.String(255), nullable=False),
        sa.Column('user_email', sa.String(255), nullable=True),
        sa.Column('action', sa.Enum(
            'create_testimony', 'update_testimony', 'delete_testimony', 'view_testimony',
            'create_event', 'update_event', 'delete_event',
            'create_timeline', 'update_timeline', 'delete_timeline',
            'detect_conflict', 'resolve_conflict',
            'user_login', 'user_logout',
            'permission_grant', 'permission_revoke',
            'data_export', 'data_deletion',
            name='audit_action'
        ), nullable=False),
        sa.Column('resource_type', sa.String(64), nullable=False),
        sa.Column('resource_id', sa.String(255), nullable=False),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('status', sa.String(32), nullable=False, server_default='success'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retention_until', sa.String(32), nullable=True),
        sa.Column('is_sensitive', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_logs_user_id', 'audit_logs', ['user_id'])
    op.create_index('ix_audit_logs_action', 'audit_logs', ['action'])
    op.create_index('ix_audit_logs_resource_type_id', 'audit_logs', ['resource_type', 'resource_id'])
    op.create_index('ix_audit_logs_is_sensitive', 'audit_logs', ['is_sensitive'])
    op.create_index('ix_audit_logs_user_id_created_at', 'audit_logs', ['user_id', 'created_at'])
    op.create_index('ix_audit_logs_action_created_at', 'audit_logs', ['action', 'created_at'])
    op.create_index('ix_audit_logs_sensitive_created_at', 'audit_logs', ['is_sensitive', 'created_at'])


def downgrade() -> None:
    """Drop RBAC and audit log tables."""
    op.drop_table('audit_logs')
    op.drop_table('user_permissions')
    op.drop_table('role_permissions')
    op.drop_table('user_roles')
    op.drop_table('permissions')
    op.drop_table('roles')
    op.drop_table('users')
