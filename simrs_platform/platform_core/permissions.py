from __future__ import annotations

from django.utils import timezone

from identity.models import RoleAssignment


def user_has_role(user, roles: set[str], *, unit_id=None) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    qs = RoleAssignment.objects.filter(
        user=user, role__in=roles, is_active=True, starts_at__lte=timezone.now()
    )
    qs = qs.filter(
        __import__("django.db.models", fromlist=["Q"]).Q(ends_at__isnull=True)
        | __import__("django.db.models", fromlist=["Q"]).Q(ends_at__gt=timezone.now())
    )
    if unit_id is not None:
        qs = qs.filter(unit_id=unit_id)
    return qs.exists()
