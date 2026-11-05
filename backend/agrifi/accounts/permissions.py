from rest_framework.permissions import BasePermission

from .models import UserRole


def user_has_role(user, *roles):
    """Persisted role check; unlike the permission classes it has no superuser bypass."""
    return bool(
        user
        and user.is_authenticated
        and UserRole.objects.filter(user=user, role__in=roles).exists()
    )


def role_required(*roles, allow_superuser=True):
    """Build a permission class allowing users who hold any of the given roles."""

    class RoleRequired(BasePermission):
        message = 'You do not have a role permitted to perform this action.'

        def has_permission(self, request, view):
            user = request.user
            if not user or not user.is_authenticated:
                return False
            if allow_superuser and user.is_superuser:
                return True
            return user_has_role(user, *roles)

    return RoleRequired


class HasRequiredRole(BasePermission):
    """Allow access only to users with a view's required_roles, or superusers."""

    message = 'You do not have a role permitted to perform this action.'

    def has_permission(self, request, view):
        user = request.user
        required_roles = getattr(view, 'required_roles', ())
        if not user or not user.is_authenticated or not required_roles:
            return False
        if user.is_superuser:
            return True
        return UserRole.objects.filter(user=user, role__in=required_roles).exists()


class IsOwnerOrHasRequiredRole(BasePermission):
    """Allow owners and explicitly privileged roles to access an individual object."""

    message = 'You do not have permission to access this resource.'

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        owner_field = getattr(view, 'owner_field', 'owner')
        owner_id = getattr(obj, f'{owner_field}_id', None)
        if owner_id is None:
            owner = getattr(obj, owner_field, None)
            owner_id = getattr(owner, 'pk', owner)
        if owner_id is not None and str(owner_id) == str(request.user.pk):
            return True

        required_roles = getattr(view, 'required_roles', ())
        if request.user.is_superuser:
            return True
        return bool(
            required_roles
            and UserRole.objects.filter(user=request.user, role__in=required_roles).exists()
        )
