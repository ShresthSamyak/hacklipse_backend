"""
Access control service for RBAC and field-level permission enforcement.
Provides role-based and field-level access control.
"""

from typing import Any, Sequence

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.models.orm.user import Permission, PermissionScope, Role, User, UserRole

logger = get_logger(__name__)


class AccessControlService:
    """
    Service for managing access control.
    Supports RBAC with role hierarchy and field-level access.
    """

    def __init__(self, db_session: AsyncSession):
        """Initialize access control service."""
        self.db = db_session

    # ──────────────────────────────────────────────────────────────────────
    # User Management
    # ──────────────────────────────────────────────────────────────────────

    async def create_user(
        self,
        email: str,
        username: str,
        full_name: str | None = None,
        password_hash: str | None = None,
        oauth_provider: str | None = None,
        oauth_id: str | None = None,
    ) -> User:
        """
        Create a new user.
        
        Args:
            email: User email
            username: User username (unique)
            full_name: Full name
            password_hash: Hashed password (None if OAuth)
            oauth_provider: OAuth provider name (google, okta, etc.)
            oauth_id: OAuth provider ID
            
        Returns:
            Created User
        """
        user = User(
            email=email,
            username=username,
            full_name=full_name,
            password_hash=password_hash,
            oauth_provider=oauth_provider,
            oauth_id=oauth_id,
            is_active=True,
        )
        self.db.add(user)
        await self.db.flush()
        logger.info("User created", user_id=str(user.id), email=email)
        return user

    async def get_user_by_id(self, user_id: str) -> User:
        """Get user by ID."""
        stmt = select(User).where(User.id == user_id)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            raise NotFoundError(f"User {user_id} not found")
        return user

    async def get_user_by_email(self, email: str) -> User | None:
        """Get user by email (returns None if not found)."""
        stmt = select(User).where(User.email == email)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ──────────────────────────────────────────────────────────────────────
    # Role Management
    # ──────────────────────────────────────────────────────────────────────

    async def create_role(
        self,
        name: str,
        description: str,
        is_builtin: bool = False,
    ) -> Role:
        """Create a new role."""
        role = Role(
            name=name,
            description=description,
            is_builtin=is_builtin,
            is_active=True,
        )
        self.db.add(role)
        await self.db.flush()
        logger.info("Role created", role_id=str(role.id), name=name)
        return role

    async def get_role_by_name(self, name: str) -> Role:
        """Get role by name."""
        stmt = select(Role).where(Role.name == name)
        result = await self.db.execute(stmt)
        role = result.scalar_one_or_none()
        if not role:
            raise NotFoundError(f"Role {name} not found")
        return role

    async def assign_role_to_user(self, user_id: str, role_id: str) -> None:
        """Assign a role to a user."""
        user = await self.get_user_by_id(user_id)
        role = await self.get_role_by_name(role_id)  # Assuming role_id is actually name for simplicity
        
        # Check if already assigned
        if role not in user.assigned_roles:
            user.assigned_roles.append(role)
            logger.info("Role assigned to user", user_id=user_id, role_id=role_id)

    async def revoke_role_from_user(self, user_id: str, role_id: str) -> None:
        """Revoke a role from a user."""
        user = await self.get_user_by_id(user_id)
        role = await self.get_role_by_name(role_id)
        
        if role in user.assigned_roles:
            user.assigned_roles.remove(role)
            logger.info("Role revoked from user", user_id=user_id, role_id=role_id)

    # ──────────────────────────────────────────────────────────────────────
    # Permission Management
    # ──────────────────────────────────────────────────────────────────────

    async def create_permission(
        self,
        name: str,
        description: str,
        resource: str,
        action: str,
        scope: PermissionScope = PermissionScope.GLOBAL,
        allowed_fields: list[str] | None = None,
        restricted_fields: list[str] | None = None,
        is_builtin: bool = False,
    ) -> Permission:
        """Create a new permission."""
        permission = Permission(
            name=name,
            description=description,
            resource=resource,
            action=action,
            scope=scope,
            allowed_fields=allowed_fields or [],
            restricted_fields=restricted_fields or [],
            is_builtin=is_builtin,
            is_active=True,
        )
        self.db.add(permission)
        await self.db.flush()
        logger.info("Permission created", permission_id=str(permission.id), name=name)
        return permission

    async def assign_permission_to_role(
        self,
        role_id: str,
        permission_id: str,
    ) -> None:
        """Assign a permission to a role."""
        stmt = select(Role).where(Role.id == role_id)
        result = await self.db.execute(stmt)
        role = result.scalar_one_or_none()
        if not role:
            raise NotFoundError(f"Role {role_id} not found")
        
        stmt = select(Permission).where(Permission.id == permission_id)
        result = await self.db.execute(stmt)
        permission = result.scalar_one_or_none()
        if not permission:
            raise NotFoundError(f"Permission {permission_id} not found")
        
        if permission not in role.permissions:
            role.permissions.append(permission)
            logger.info("Permission assigned to role", role_id=role_id, permission_id=permission_id)

    # ──────────────────────────────────────────────────────────────────────
    # Permission Checking
    # ──────────────────────────────────────────────────────────────────────

    async def has_permission(
        self,
        user_id: str,
        resource: str,
        action: str,
        scope: PermissionScope = PermissionScope.GLOBAL,
    ) -> bool:
        """
        Check if user has a specific permission.
        
        Args:
            user_id: User ID
            resource: Resource type (testimony, event, etc.)
            action: Action type (read, write, delete, etc.)
            scope: Permission scope (GLOBAL, PROJECT, RESOURCE)
            
        Returns:
            True if user has permission, False otherwise
        """
        try:
            user = await self.get_user_by_id(user_id)
        except NotFoundError:
            return False
        
        # Check direct user permissions
        for perm in user.direct_permissions:
            if (perm.resource == resource and  perm.action == action and 
                perm.scope == scope and perm.is_active):
                return True
        
        # Check role permissions
        for role in user.assigned_roles:
            if not role.is_active:
                continue
            for perm in role.permissions:
                if (perm.resource == resource and perm.action == action and 
                    perm.scope == scope and perm.is_active):
                    return True
        
        return False

    async def get_user_permissions(self, user_id: str) -> list[str]:
        """Get all permission names for a user."""
        try:
            user = await self.get_user_by_id(user_id)
        except NotFoundError:
            return []
        
        permissions = set()
        
        # Direct permissions
        for perm in user.direct_permissions:
            if perm.is_active:
                permissions.add(perm.name)
        
        # Role permissions
        for role in user.assigned_roles:
            if role.is_active:
                for perm in role.permissions:
                    if perm.is_active:
                        permissions.add(perm.name)
        
        return sorted(list(permissions))

    async def get_user_roles(self, user_id: str) -> list[str]:
        """Get all role names for a user."""
        try:
            user = await self.get_user_by_id(user_id)
        except NotFoundError:
            return []
        
        return [role.name for role in user.assigned_roles if role.is_active]

    # ──────────────────────────────────────────────────────────────────────
    # Field-Level Access Control
    # ──────────────────────────────────────────────────────────────────────

    async def filter_fields(
        self,
        user_id: str,
        resource: str,
        action: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Filter response fields based on user permissions.
        
        Args:
            user_id: User ID
            resource: Resource type
            action: Action type
            data: Full response data
            
        Returns:
            Filtered data with only allowed fields
        """
        # Get user permissions
        user = await self.get_user_by_id(user_id)
        
        # Find applicable permission
        applicable_perm = None
        for perm in user.direct_permissions:
            if (perm.resource == resource and perm.action == action and perm.is_active):
                applicable_perm = perm
                break
        
        if not applicable_perm:
            for role in user.assigned_roles:
                if not role.is_active:
                    continue
                for perm in role.permissions:
                    if (perm.resource == resource and perm.action == action and perm.is_active):
                        applicable_perm = perm
                        break
                if applicable_perm:
                    break
        
        if not applicable_perm:
            return {}  # No permission, return empty
        
        # If no field restrictions, return all
        if not applicable_perm.allowed_fields and not applicable_perm.restricted_fields:
            return data
        
        # Apply field filters
        filtered = {}
        for key, value in data.items():
            # Check allowed fields (whitelist)
            if applicable_perm.allowed_fields:
                if key in applicable_perm.allowed_fields:
                    filtered[key] = value
            # Check restricted fields (blacklist)
            elif applicable_perm.restricted_fields:
                if key not in applicable_perm.restricted_fields:
                    filtered[key] = value
            else:
                filtered[key] = value
        
        return filtered

    # ──────────────────────────────────────────────────────────────────────
    # Bootstrap: Initialize default roles and permissions
    # ──────────────────────────────────────────────────────────────────────

    async def bootstrap_default_roles_and_permissions(self) -> None:
        """
        Create default RBAC configuration.
        Call once during application startup.
        """
        # Check if already bootstrapped
        stmt = select(Role).where(Role.is_builtin == True)
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            logger.info("Default roles already bootstrapped")
            return
        
        # Default permissions
        permissions_config = [
            # Testimony permissions
            ("testimony:read", "Read testimonies", "testimony", "read", PermissionScope.GLOBAL),
            ("testimony:create", "Create testimonies", "testimony", "create", PermissionScope.GLOBAL),
            ("testimony:update", "Update testimonies", "testimony", "update", PermissionScope.GLOBAL),
            ("testimony:delete", "Delete testimonies", "testimony", "delete", PermissionScope.GLOBAL),
            
            # Event permissions
            ("event:read", "Read events", "event", "read", PermissionScope.GLOBAL),
            ("event:create", "Create events", "event", "create", PermissionScope.GLOBAL),
            ("event:update", "Update events", "event", "update", PermissionScope.GLOBAL),
            
            # Timeline permissions
            ("timeline:read", "Read timelines", "timeline", "read", PermissionScope.GLOBAL),
            ("timeline:create", "Create timelines", "timeline", "create", PermissionScope.GLOBAL),
            ("timeline:update", "Update timelines", "timeline", "update", PermissionScope.GLOBAL),
            
            # Admin permissions
            ("user:manage", "Manage users", "user", "manage", PermissionScope.GLOBAL),
            ("role:manage", "Manage roles", "role", "manage", PermissionScope.GLOBAL),
            ("audit:read", "Read audit logs", "audit", "read", PermissionScope.GLOBAL),
        ]
        
        perms_map = {}
        for perm_name, desc, res, action, scope in permissions_config:
            perm = await self.create_permission(
                name=perm_name,
                description=desc,
                resource=res,
                action=action,
                scope=scope,
                is_builtin=True,
            )
            perms_map[perm_name] = perm
        
        # Default roles
        admin_role = await self.create_role(
            name=UserRole.ADMIN.value,
            description="Full system access",
            is_builtin=True,
        )
        
        investigator_role = await self.create_role(
            name=UserRole.INVESTIGATOR.value,
            description="Can create and analyze cases",
            is_builtin=True,
        )
        
        analyst_role = await self.create_role(
            name=UserRole.ANALYST.value,
            description="Can view and analyze data",
            is_builtin=True,
        )
        
        viewer_role = await self.create_role(
            name=UserRole.VIEWER.value,
            description="Read-only access",
            is_builtin=True,
        )
        
        # Assign permissions to roles
        admin_perms = list(perms_map.values())
        for perm in admin_perms:
            admin_role.permissions.append(perm)
        
        investigator_perms = [
            perms_map.get("testimony:create"),
            perms_map.get("testimony:update"),
            perms_map.get("testimony:read"),
            perms_map.get("event:create"),
            perms_map.get("event:read"),
            perms_map.get("timeline:create"),
            perms_map.get("timeline:read"),
            perms_map.get("audit:read"),
        ]
        for perm in investigator_perms:
            if perm:
                investigator_role.permissions.append(perm)
        
        analyst_perms = [
            perms_map.get("testimony:read"),
            perms_map.get("event:read"),
            perms_map.get("timeline:read"),
        ]
        for perm in analyst_perms:
            if perm:
                analyst_role.permissions.append(perm)
        
        viewer_perms = [
            perms_map.get("testimony:read"),
            perms_map.get("event:read"),
            perms_map.get("timeline:read"),
        ]
        for perm in viewer_perms:
            if perm:
                viewer_role.permissions.append(perm)
        
        logger.info("Bootstrap complete: default roles and permissions created")
