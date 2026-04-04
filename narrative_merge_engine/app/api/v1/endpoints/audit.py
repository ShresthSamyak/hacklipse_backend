"""
API endpoints for audit logging and compliance.
Provides audit history, logs, and GDPR data export functionality.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Query

from app.api.deps import DBDep, CurrentUser
from app.core.logging import get_logger
from app.services.audit_service import AuditLogService

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/audit", tags=["Audit & Compliance"])


@router.get("/logs/user/{user_id}")
async def get_user_audit_logs(
    user_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = None,
    db: DBDep = None,
) -> dict:
    """Get audit logs for a specific user."""
    if db is None:
        return {"error": "Database connection failed"}
    
    audit_service = AuditLogService(db)
    logs, total = await audit_service.get_user_audit_history(
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    
    return {
        "entries": [
            {
                "id": str(log.id),
                "created_at": log.created_at.isoformat(),
                "user_id": log.user_id,
                "user_email": log.user_email,
                "action": log.action.value,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "description": log.description,
                "status": log.status,
                "ip_address": log.ip_address,
                "is_sensitive": log.is_sensitive,
            }
            for log in logs
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/logs/resource/{resource_type}/{resource_id}")
async def get_resource_audit_logs(
    resource_type: str,
    resource_id: str,
    limit: int = Query(100, ge=1, le=1000),
    db: DBDep = None,
) -> dict:
    """Get audit history for a specific resource."""
    if db is None:
        return {"error": "Database connection failed"}
    
    audit_service = AuditLogService(db)
    logs = await audit_service.get_resource_audit_history(
        resource_type=resource_type,
        resource_id=resource_id,
        limit=limit,
    )
    
    return {
        "resource": f"{resource_type}:{resource_id}",
        "entries": [
            {
                "id": str(log.id),
                "created_at": log.created_at.isoformat(),
                "user_id": log.user_id,
                "action": log.action.value,
                "description": log.description,
                "status": log.status,
            }
            for log in logs
        ],
    }


@router.get("/logs/sensitive")
async def get_sensitive_operations(
    days: int = Query(90, ge=1, le=365),
    limit: int = Query(1000, ge=1, le=10000),
    db: DBDep = None,
) -> dict:
    """Get all operations involving sensitive/PII data."""
    if db is None:
        return {"error": "Database connection failed"}
    
    audit_service = AuditLogService(db)
    logs = await audit_service.get_sensitive_operations(days=days, limit=limit)
    
    return {
        "period_days": days,
        "sensitive_operations": [
            {
                "id": str(log.id),
                "created_at": log.created_at.isoformat(),
                "user_id": log.user_id,
                "user_email": log.user_email,
                "action": log.action.value,
                "resource_type": log.resource_type,
                "description": log.description,
            }
            for log in logs
        ],
        "total": len(logs),
    }


@router.post("/export")
async def export_audit_trail(
    user_id: str | None = Query(None),
    resource_type: str | None = Query(None),
    days: int = Query(365, ge=1, le=3650),
    include_sensitive: bool = Query(True),
    db: DBDep = None,
) -> dict:
    """Export audit trail for compliance/investigation."""
    if db is None:
        return {"error": "Database connection failed"}
    
    audit_service = AuditLogService(db)
    entries = await audit_service.export_audit_trail(
        user_id=user_id,
        resource_type=resource_type,
        days=days,
        include_sensitive=include_sensitive,
    )
    
    return {
        "export_timestamp": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "user_id": user_id,
            "resource_type": resource_type,
            "days": days,
            "include_sensitive": include_sensitive,
        },
        "entry_count": len(entries),
        "entries": entries,
    }


@router.get("/stats")
async def get_audit_statistics(
    days: int = Query(30, ge=1, le=365),
) -> dict:
    """Get audit log statistics."""
    return {
        "period_days": days,
        "total_operations": 0,
        "by_action": {},
        "by_user": {},
        "by_resource": {},
        "sensitive_operations_count": 0,
    }


@router.post("/cleanup")
async def cleanup_expired_logs(
    db: DBDep = None,
) -> dict:
    """Clean up audit logs that have exceeded retention period."""
    if db is None:
        return {"error": "Database connection failed"}
    
    audit_service = AuditLogService(db)
    deleted_count = await audit_service.cleanup_expired_logs()
    await db.commit()
    
    logger.info("Audit log cleanup performed", count=deleted_count)
    
    return {
        "deleted_count": deleted_count,
        "message": f"Cleaned up {deleted_count} expired audit logs",
    }
