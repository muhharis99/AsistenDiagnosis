from django.contrib import admin

from terminology.models import CodeSystem, CodeTerm


@admin.register(CodeSystem)
class CodeSystemAdmin(admin.ModelAdmin):
    list_display = ("name", "uri", "version", "is_verified", "effective_from", "effective_to")
    list_filter = ("is_verified",)
    search_fields = ("name", "uri")


@admin.register(CodeTerm)
class CodeTermAdmin(admin.ModelAdmin):
    list_display = ("system", "code", "display", "is_active")
    list_filter = ("system", "is_active")
    search_fields = ("code", "display")
