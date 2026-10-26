from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from identity.models import RoleAssignment
from organization.models import UserUnitAssignment


def has_scoped_role(user, roles: set[str], *, unit_id: str) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    now = timezone.now()
    assigned = UserUnitAssignment.objects.filter(
        user=user, unit_id=unit_id, is_active=True, unit__is_active=True
    ).exists()
    global_admin = (
        RoleAssignment.objects.filter(
            user=user,
            role=RoleAssignment.Role.SYSTEM_ADMIN,
            unit__isnull=True,
            is_active=True,
            starts_at__lte=now,
        )
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
        .exists()
    )
    if global_admin:
        return True
    if not assigned:
        return False
    return (
        RoleAssignment.objects.filter(
            user=user, role__in=roles, unit_id=unit_id, is_active=True, starts_at__lte=now
        )
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
        .exists()
    )


def has_any_scoped_role(user, roles: set[str]) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    now = timezone.now()
    active_units = UserUnitAssignment.objects.filter(
        user=user, is_active=True, unit__is_active=True
    ).values("unit_id")
    return (
        RoleAssignment.objects.filter(user=user, role__in=roles, is_active=True, starts_at__lte=now)
        .filter(Q(ends_at__isnull=True) | Q(ends_at__gt=now))
        .filter(
            Q(unit_id__in=active_units)
            | Q(role=RoleAssignment.Role.SYSTEM_ADMIN, unit__isnull=True)
        )
        .exists()
    )
