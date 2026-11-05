from agrifi.accounts.models import UserRole
from agrifi.accounts.permissions import role_required, user_has_role
from rest_framework.permissions import SAFE_METHODS, BasePermission


def is_ops_admin(user):
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user_has_role(user, UserRole.Role.OPERATIONS_ADMIN))
    )


IsOperationsAdmin = role_required(UserRole.Role.OPERATIONS_ADMIN)
IsFarmer = role_required(UserRole.Role.FARMER, allow_superuser=False)


class ReadOnlyOrOperationsAdmin(BasePermission):
    """Authenticated users may read; only operations administrators may write."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.method in SAFE_METHODS or is_ops_admin(request.user)
