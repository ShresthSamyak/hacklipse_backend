"""
ORM models: RBAC (Role-Based Access Control)
User, Role, Permission models for field-level access control.
"""

from enum import Enum as PyEnum

from sqlalchemy import Boolean, Enum, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserRole(str, PyEnum):
    """Predefined user roles (can extend with custom roles in DB)."""
    ADMIN = "admin"                    # Full access, can manage users
    INVESTIGATOR = "investigator"      # Create/edit cases, generate reports
    ANALYST = "analyst"                # View/analyze data, no modifications
    VIEWER = "viewer"                  # Read-only access to assigned cases
    SYSTEM = "system"                  # Automated operations


class PermissionScope(str, PyEnum):
    """Scope of permission granularity."""
    GLOBAL = "global"                  # All resources
    PROJECT = "project"                # All resources in a project/case
    RESOURCE = "resource"              # Specific resource


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    User account with RBAC support.
    Tracks authentication, roles, and audit trail.
    """
    __tablename__ = "users"

    # Authentication
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)  # None if OAuth/SAML
    
    # Profile
    full_name: Mapped[str] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Status
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    is_verified: Mapped[bool] = mapped_column(default=False)
    
    # OAuth/SAML
    oauth_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)  # "google", "okta", "azure", etc.
    oauth_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    
    # MFA
    mfa_enabled: Mapped[bool] = mapped_column(default=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(256), nullable=True)  # Encrypted TOTP secret
    
    # Password management
    password_changed_at: Mapped[str | None] = mapped_column(String(32), nullable=True)  # ISO datetime
    password_expires_at: Mapped[str | None] = mapped_column(String(32), nullable=True)  # ISO datetime
    last_login_at: Mapped[str | None] = mapped_column(String(32), nullable=True)  # ISO datetime
    
    # Flexible metadata
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    
    # Relationships
    assigned_roles: Mapped[list["Role"]] = relationship(
        "Role",
        secondary="user_roles",
        back_populates="users",
        lazy="selectin",
    )
    direct_permissions: Mapped[list["Permission"]] = relationship(
        "Permission",
        secondary="user_permissions",
        back_populates="users",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_users_email", "email"),
        Index("ix_users_is_active", "is_active"),
        UniqueConstraint("oauth_provider", "oauth_id", name="uc_oauth_provider_id"),
    )


class Role(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Role definition with associated permissions.
    Predefined roles: admin, investigator, analyst, viewer.
    """
    __tablename__ = "roles"

    # Core fields
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Built-in role flag (cannot be deleted)
    is_builtin: Mapped[bool] = mapped_column(default=False, index=True)
    
    # Visibility
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    
    # Flexible metadata
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    
    # Relationships
    users: Mapped[list["User"]] = relationship(
        "User",
        secondary="user_roles",
        back_populates="assigned_roles",
        lazy="selectin",
    )
    permissions: Mapped[list["Permission"]] = relationship(
        "Permission",
        secondary="role_permissions",
        back_populates="roles",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_roles_name", "name"),
        Index("ix_roles_is_builtin", "is_builtin"),
    )


class Permission(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Granular permission definition.
    Examples: "testimony:read", "testimony:create:all", "event:update:own"
    Scope: GLOBAL (all), PROJECT (all in project), RESOURCE (specific resource)
    """
    __tablename__ = "permissions"

    # Permission identifier (e.g., "testimony:create")
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Resource and action
    resource: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # "testimony", "event", "timeline", etc.
    action: Mapped[str] = mapped_column(String(64), nullable=False)  # "read", "create", "update", "delete"
    
    # Scope of permission
    scope: Mapped[PermissionScope] = mapped_column(
        Enum(PermissionScope),
        nullable=False,
        default=PermissionScope.GLOBAL,
    )
    
    # Optional resource restriction
    resource_id_pattern: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Regex: "own", "assigned_to:user_id", etc.
    
    # Field-level access (for responses, what fields are visible)
    allowed_fields: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)  # None = all fields
    restricted_fields: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)  # Fields to exclude
    
    # Built-in permission flag
    is_builtin: Mapped[bool] = mapped_column(default=False, index=True)
    
    # Active/inactive
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    
    # Flexible metadata
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    
    # Relationships
    roles: Mapped[list["Role"]] = relationship(
        "Role",
        secondary="role_permissions",
        back_populates="permissions",
        lazy="selectin",
    )
    users: Mapped[list["User"]] = relationship(
        "User",
        secondary="user_permissions",
        back_populates="direct_permissions",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_permissions_name", "name"),
        Index("ix_permissions_resource_action", "resource", "action"),
    )

    @property
    def full_name(self) -> str:
        """Human-readable permission name (e.g., 'testimony:create:global')."""
        return f"{self.resource}:{self.action}:{self.scope.value}"

