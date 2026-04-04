"""
Permission decorators for FastAPI endpoints.
Provides @require_permission and @require_role decorators for access control.
"""

from functools import wraps
from typing import Any, Callable

from fastapi import Depends, Request

from app.api.deps import get_current_user, get_db_session
from app.core.exceptions import ForbiddenError
from app.models.orm.user import PermissionScope
from app.services.access_control_service import AccessControlService


def require_permission(
    resource: str,
    action: str,
    scope: PermissionScope = PermissionScope.GLOBAL,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator to enforce permission requirements on FastAPI endpoints.
    
    Usage:
        @router.post("/testimonies")
        @require_permission("testimony", "create")
        async def create_testimony(data: TestimonyCreate, user: User = Depends(get_current_user)):
            ...
    
    Args:
        resource: Resource type (testimony, event, timeline, etc.)
        action: Action type (read, create, update, delete, manage)
        scope: Permission scope (GLOBAL, PROJECT, RESOURCE)
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract user and db from kwargs (typically from Depends)
            user = kwargs.get("user") or kwargs.get("current_user")
            db_session = kwargs.get("db_session")
            
            if not user:
                raise ForbiddenError("User not authenticated")
            
            if not db_session:
                raise ForbiddenError("Database session not available")
            
            # Check permission
            ac_service = AccessControlService(db_session)
            has_perm = await ac_service.has_permission(
                user_id=str(user.id),
                resource=resource,
                action=action,
                scope=scope,
            )
            
            if not has_perm:
                raise ForbiddenError(
                    f"User does not have permission: {resource}:{action}:{scope.value}"
                )
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


def require_role(roles: list[str] | str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator to enforce role requirements on FastAPI endpoints.
    
    Usage:
        @router.delete("/users/{user_id}")
        @require_role(["admin"])
        async def delete_user(user_id: str, user: User = Depends(get_current_user)):
            ...
    
    Args:
        roles: Required role(s) - list or single string
    """
    if isinstance(roles, str):
        roles = [roles]
    
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            user = kwargs.get("user") or kwargs.get("current_user")
            db_session = kwargs.get("db_session")
            
            if not user:
                raise ForbiddenError("User not authenticated")
            
            if not db_session:
                raise ForbiddenError("Database session not available")
            
            # Check roles
            ac_service = AccessControlService(db_session)
            user_roles = await ac_service.get_user_roles(str(user.id))
            
            has_role = any(role in user_roles for role in roles)
            if not has_role:
                raise ForbiddenError(f"User must have one of roles: {', '.join(roles)}")
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator


def require_admin() -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator to require admin role.
    
    Usage:
        @router.get("/admin/stats")
        @require_admin()
        async def get_admin_stats(user: User = Depends(get_current_user)):
            ...
    """
    return require_role("admin")
