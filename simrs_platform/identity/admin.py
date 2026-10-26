from django.contrib import admin

from identity.models import RoleAssignment


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "unit", "is_active", "starts_at", "ends_at")
    list_filter = ("role", "is_active", "unit")
    search_fields = ("user__username",)
