"""
ORM model: AuditLog
Immutable audit log for compliance and investigation tracking.
Records all operations on sensitive data with GDPR compliance.
"""

from enum import Enum as PyEnum

from sqlalchemy import Enum, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AuditAction(str, PyEnum):
    """Enumeration of auditable actions."""
    # Testimony operations
    CREATE_TESTIMONY = "create_testimony"
    UPDATE_TESTIMONY = "update_testimony"
    DELETE_TESTIMONY = "delete_testimony"
    VIEW_TESTIMONY = "view_testimony"
    
    # Event operations
    CREATE_EVENT = "create_event"
    UPDATE_EVENT = "update_event"
    DELETE_EVENT = "delete_event"
    
    # Timeline operations
    CREATE_TIMELINE = "create_timeline"
    UPDATE_TIMELINE = "update_timeline"
    DELETE_TIMELINE = "delete_timeline"
    
    # Conflict operations
    DETECT_CONFLICT = "detect_conflict"
    RESOLVE_CONFLICT = "resolve_conflict"
    
    # User & Access
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    PERMISSION_GRANT = "permission_grant"
    PERMISSION_REVOKE = "permission_revoke"
    
    # Data retention/compliance
    DATA_EXPORT = "data_export"
    DATA_DELETION = "data_deletion"


class AuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Immutable audit log entry.
    One entry per operation on sensitive data.
    Designed for compliance and forensic analysis.
    """
    __tablename__ = "audit_logs"

    # Who performed the action
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_email: Mapped[str] = mapped_column(String(255), nullable=True)
    
    # What action
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction),
        nullable=False,
        index=True,
    )
    
    # What resource
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    
    # Context
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv6 compatible
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Action details
    description: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Before/after for mutation tracking
    # Stored as encrypted JSON in production
    changes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # {old: {...}, new: {...}}
    
    # Status
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="success")  # success, failure, partial
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Compliance
    retention_until: Mapped[str | None] = mapped_column(String(32), nullable=True)  # ISO datetime, null = indefinite
    is_sensitive: Mapped[bool] = mapped_column(default=False, index=True)  # PII/sensitive data involved
    
    # Flexible metadata
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    # Indexes for efficient querying
    __table_args__ = (
        Index("ix_audit_logs_user_id_created_at", "user_id", "created_at"),
        Index("ix_audit_logs_action_created_at", "action", "created_at"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
        Index("ix_audit_logs_sensitive_created_at", "is_sensitive", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog {self.action} on {self.resource_type}:{self.resource_id} "
            f"by {self.user_id} at {self.created_at}>"
        )
