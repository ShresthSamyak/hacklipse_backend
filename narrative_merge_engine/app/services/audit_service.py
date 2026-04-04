"""
Audit logging service for compliance and forensic tracking.
Provides high-level API for recording and querying audit logs.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.orm.audit_log import AuditAction, AuditLog

logger = get_logger(__name__)


class AuditLogService:
    """
    Service for managing audit logs.
    Handles creation, querying, retention policies, and compliance exports.
    """

    def __init__(self, db_session: AsyncSession):
        """Initialize audit service with database session."""
        self.db = db_session

    async def log(
        self,
        user_id: str,
        action: AuditAction,
        resource_type: str,
        resource_id: str,
        description: str,
        *,
        user_email: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        changes: dict | None = None,
        status: str = "success",
        error_message: str | None = None,
        is_sensitive: bool = False,
        retention_days: int | None = None,
        meta: dict | None = None,
    ) -> AuditLog:
        """
        Create an audit log entry.
        
        Args:
            user_id: ID of user who performed the action
            action: Type of action (AuditAction enum)
            resource_type: Type of resource affected (testimony, event, timeline, etc.)
            resource_id: ID of the resource
            description: Human-readable description of the action
            user_email: Email of the user (for audit trail queries)
            ip_address: IP address from which action was performed
            user_agent: User-Agent string from the request
            changes: Before/after state changes (dict with 'old' and 'new' keys)
            status: Status of the action (success, failure, partial)
            error_message: Error message if status is failure
            is_sensitive: Flag if PII or sensitive data involved
            retention_days: Override default retention (None = indefinite)
            meta: Additional metadata as dict
            
        Returns:
            Created AuditLog entry
        """
        changes = changes or {}
        meta = meta or {}
        
        # Calculate retention expiry if applicable
        retention_until = None
        if retention_days is not None and retention_days > 0:
            expiry = datetime.now(timezone.utc) + timedelta(days=retention_days)
            retention_until = expiry.isoformat()
        
        # Create audit log entry
        audit_entry = AuditLog(
            user_id=user_id,
            user_email=user_email,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            user_agent=user_agent,
            description=description,
            changes=changes,
            status=status,
            error_message=error_message,
            is_sensitive=is_sensitive,
            retention_until=retention_until,
            meta=meta,
        )
        
        self.db.add(audit_entry)
        await self.db.flush()  # Ensure ID is generated
        
        logger.info(
            "Audit log created",
            action=action,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            sensitive=is_sensitive,
        )
        
        return audit_entry

    async def get_user_audit_history(
        self,
        user_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[Sequence[AuditLog], int]:
        """
        Get audit history for a specific user.
        
        Args:
            user_id: User ID to query
            limit: Maximum number of entries to return
            offset: Pagination offset
            
        Returns:
            Tuple of (audit logs, total count)
        """
        # Count total
        count_stmt = select(lambda: None).select_from(AuditLog).where(AuditLog.user_id == user_id).with_entities(lambda: __import__('sqlalchemy').func.count(AuditLog.id))
        count = await self.db.scalar(count_stmt)
        
        # Get entries
        stmt = (
            select(AuditLog)
            .where(AuditLog.user_id == user_id)
            .order_by(desc(AuditLog.created_at))
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        entries = result.scalars().all()
        
        return entries, count or 0

    async def get_resource_audit_history(
        self,
        resource_type: str,
        resource_id: str,
        limit: int = 100,
    ) -> Sequence[AuditLog]:
        """
        Get audit history for a specific resource.
        
        Args:
            resource_type: Type of resource (testimony, event, etc.)
            resource_id: ID of the resource
            limit: Maximum number of entries to return
            
        Returns:
            List of audit logs
        """
        stmt = (
            select(AuditLog)
            .where(
                and_(
                    AuditLog.resource_type == resource_type,
                    AuditLog.resource_id == resource_id,
                )
            )
            .order_by(desc(AuditLog.created_at))
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_action_audit_history(
        self,
        action: AuditAction,
        days: int = 30,
        limit: int = 1000,
    ) -> Sequence[AuditLog]:
        """
        Get audit history for a specific action type within a time window.
        
        Args:
            action: Action type to query
            days: Number of days to look back
            limit: Maximum number of entries
            
        Returns:
            List of audit logs
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            select(AuditLog)
            .where(
                and_(
                    AuditLog.action == action,
                    AuditLog.created_at >= cutoff,
                )
            )
            .order_by(desc(AuditLog.created_at))
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_sensitive_operations(
        self,
        days: int = 90,
        limit: int = 1000,
    ) -> Sequence[AuditLog]:
        """
        Get all operations involving sensitive/PII data.
        
        Args:
            days: Number of days to look back
            limit: Maximum number of entries
            
        Returns:
            List of audit logs with sensitive operations
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            select(AuditLog)
            .where(
                and_(
                    AuditLog.is_sensitive == True,
                    AuditLog.created_at >= cutoff,
                )
            )
            .order_by(desc(AuditLog.created_at))
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def cleanup_expired_logs(self) -> int:
        """
        Delete audit logs that have exceeded their retention period.
        GDPR: Implements data retention policies.
        
        Returns:
            Number of logs deleted
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        
        # Find expired entries
        stmt = select(AuditLog).where(
            and_(
                AuditLog.retention_until.is_not(None),
                AuditLog.retention_until <= now_iso,
            )
        )
        result = await self.db.execute(stmt)
        expired_logs = result.scalars().all()
        
        count = len(expired_logs)
        for log in expired_logs:
            await self.db.delete(log)
        
        if count > 0:
            logger.info("Cleaned up expired audit logs", count=count)
        
        return count

    async def export_audit_trail(
        self,
        user_id: str | None = None,
        resource_type: str | None = None,
        days: int = 365,
        include_sensitive: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Export audit trail for compliance/investigation.
        GDPR: Supports right-to-audit and data export requests.
        
        Args:
            user_id: Filter by user (None = all users)
            resource_type: Filter by resource (None = all resources)
            days: Number of days to export
            include_sensitive: Include sensitive operations
            
        Returns:
            List of audit log entries as dictionaries
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        conditions = [AuditLog.created_at >= cutoff]
        
        if user_id:
            conditions.append(AuditLog.user_id == user_id)
        
        if resource_type:
            conditions.append(AuditLog.resource_type == resource_type)
        
        if not include_sensitive:
            conditions.append(AuditLog.is_sensitive == False)
        
        stmt = (
            select(AuditLog)
            .where(and_(*conditions))
            .order_by(desc(AuditLog.created_at))
        )
        result = await self.db.execute(stmt)
        entries = result.scalars().all()
        
        # Serialize to dicts
        return [
            {
                "id": str(entry.id),
                "created_at": entry.created_at.isoformat(),
                "user_id": entry.user_id,
                "user_email": entry.user_email,
                "action": entry.action.value,
                "resource_type": entry.resource_type,
                "resource_id": entry.resource_id,
                "description": entry.description,
                "status": entry.status,
                "ip_address": entry.ip_address,
                "is_sensitive": entry.is_sensitive,
                "meta": entry.meta,
            }
            for entry in entries
        ]
