from django.contrib import admin
from organization.models import OrganizationUnit, UserUnitAssignment

@admin.register(OrganizationUnit)
class OrganizationUnitAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "unit_type", "parent", "is_active")
    list_filter = ("unit_type", "is_active")
    search_fields = ("code", "name")

@admin.register(UserUnitAssignment)
class UserUnitAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "unit", "is_active", "assigned_at")
    list_filter = ("is_active", "unit__unit_type")
    search_fields = ("user__username", "unit__code", "unit__name")
