from django.contrib import admin
from platform_core.models import AuditEvent

@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("sequence", "created_at", "actor", "event_type", "subject_type", "subject_id")
    list_filter = ("event_type", "subject_type", "created_at")
    search_fields = ("subject_type", "subject_id", "event_type")
    readonly_fields = tuple(field.name for field in AuditEvent._meta.fields)
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False
