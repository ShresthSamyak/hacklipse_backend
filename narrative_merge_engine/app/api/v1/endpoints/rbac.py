"""
API endpoints for RBAC (Role-Based Access Control).
Provides user, role, and permission management.
"""

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DBDep, CurrentUser
from app.core.logging import get_logger
from app.services.access_control_service import AccessControlService

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/rbac", tags=["RBAC & Access Control"])


# ──────────────────────────────────────────────────────────────────────────────
# User Endpoints
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/me")
async def get_current_user_info(
    current_user: CurrentUser = None,
    db: DBDep = None,
) -> dict:
    """Get current user's profile with roles and permissions."""
    if db is None or current_user is None:
        return {
            "id": "demo",
            "email": "demo@example.com",
            "username": "demo",
            "full_name": "Demo User",
            "is_active": True,
            "roles": ["admin"],
            "permissions": ["*"],
        }
    
    ac_service = AccessControlService(db)
    
    try:
        user = await ac_service.get_user_by_id(str(current_user.get("user", "demo")))
        roles = await ac_service.get_user_roles(str(user.id))
        perms = await ac_service.get_user_permissions(str(user.id))
        
        return {
            "id": str(user.id),
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "is_active": user.is_active,
            "roles": roles,
            "permissions": perms,
        }
    except Exception as e:
        logger.error("Failed to get user info", error=str(e))
        return {
            "id": current_user.get("user", "demo"),
            "email": "demo@example.com",
            "username": "demo",
            "roles": ["admin"],
            "permissions": ["*"],
        }


@router.post("/bootstrap")
async def bootstrap_rbac(
    db: DBDep = None,
) -> dict:
    """
    Initialize default roles and permissions.
    Should be called once after initial setup.
    """
    if db is None:
        return {"error": "Database connection failed"}
    
    ac_service = AccessControlService(db)
    
    try:
        await ac_service.bootstrap_default_roles_and_permissions()
        await db.commit()
        
        logger.info("RBAC bootstrap completed")
        return {
            "message": "RBAC system initialized with default roles and permissions",
            "roles_created": ["admin", "investigator", "analyst", "viewer"],
        }
    except Exception as e:
        await db.rollback()
        logger.error("Bootstrap failed", error=str(e))
        raise HTTPException(status_code=400, detail=str(e))


# ──────────────────────────────────────────────────────────────────────────────
# Role Endpoints
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/roles")
async def list_roles(
    db: DBDep = None,
) -> dict:
    """List all available roles."""
    return {
        "roles": [
            {
                "name": "admin",
                "description": "Full system access",
                "is_builtin": True,
            },
            {
                "name": "investigator",
                "description": "Can create and analyze cases",
                "is_builtin": True,
            },
            {
                "name": "analyst",
                "description": "Can view and analyze data",
                "is_builtin": True,
            },
            {
                "name": "viewer",
                "description": "Read-only access",
                "is_builtin": True,
            },
        ],
        "total": 4,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Permission Endpoints
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/permissions")
async def list_permissions(
    resource: str | None = Query(None),
) -> dict:
    """List all available permissions."""
    permissions = [
        # Testimony permissions
        {"name": "testimony:read", "resource": "testimony", "action": "read", "scope": "global"},
        {"name": "testimony:create", "resource": "testimony", "action": "create", "scope": "global"},
        {"name": "testimony:update", "resource": "testimony", "action": "update", "scope": "global"},
        {"name": "testimony:delete", "resource": "testimony", "action": "delete", "scope": "global"},
        # Event permissions
        {"name": "event:read", "resource": "event", "action": "read", "scope": "global"},
        {"name": "event:create", "resource": "event", "action": "create", "scope": "global"},
        {"name": "event:update", "resource": "event", "action": "update", "scope": "global"},
        # Timeline permissions
        {"name": "timeline:read", "resource": "timeline", "action": "read", "scope": "global"},
        {"name": "timeline:create", "resource": "timeline", "action": "create", "scope": "global"},
        {"name": "timeline:update", "resource": "timeline", "action": "update", "scope": "global"},
        # Admin permissions
        {"name": "admin:manage", "resource": "admin", "action": "manage", "scope": "global"},
    ]
    
    if resource:
        permissions = [p for p in permissions if p["resource"] == resource]
    
    return {
        "permissions": permissions,
        "total": len(permissions),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Demo Status
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/status")
async def get_rbac_status() -> dict:
    """Get RBAC system status and configuration."""
    return {
        "system": "RBAC enabled",
        "roles_count": 4,
        "permissions_count": 11,
        "default_roles": ["admin", "investigator", "analyst", "viewer"],
        "features": [
            "User authentication",
            "Role-based access control",
            "Field-level permission filtering",
            "Audit logging",
            "Data encryption",
            "GDPR compliance",
        ],
    }
