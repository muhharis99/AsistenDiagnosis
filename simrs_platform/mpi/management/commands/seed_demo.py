from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from organization.models import OrganizationUnit, UserUnitAssignment
from identity.models import RoleAssignment

class Command(BaseCommand):
    help = "Create clearly fictional Phase 1 demo structure and test account."

    def handle(self, *args, **options):
        User = get_user_model()
        unit, _ = OrganizationUnit.objects.get_or_create(
            code="DEMO-UGD", defaults={"name": "Unit Demo IGD", "unit_type": OrganizationUnit.UnitType.SERVICE}
        )
        user, created = User.objects.get_or_create(username="registrar_demo", defaults={"is_staff": False})
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
            self.stdout.write(self.style.WARNING(
                "Created registrar_demo with unusable password. Set a password locally with: "
                "python manage.py changepassword registrar_demo"
            ))
        UserUnitAssignment.objects.get_or_create(user=user, unit=unit)
        RoleAssignment.objects.get_or_create(user=user, role=RoleAssignment.Role.REGISTRAR, unit=unit)
        self.stdout.write(self.style.SUCCESS("Synthetic demo unit and account assignment are ready."))
