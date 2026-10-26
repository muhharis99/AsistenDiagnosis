from django.contrib import admin
from cashier.models import Invoice, InvoiceLine, InvoicePayment, TariffItem

@admin.register(TariffItem)
class TariffItemAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category", "unit_price", "effective_from", "effective_to", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("code", "name")

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_no", "registration", "status", "total_amount", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("invoice_no", "registration__registration_no")
    readonly_fields = tuple(field.name for field in Invoice._meta.fields)
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

@admin.register(InvoiceLine)
class InvoiceLineAdmin(admin.ModelAdmin):
    list_display = ("invoice", "tariff_code_snapshot", "quantity", "line_total")
    readonly_fields = tuple(field.name for field in InvoiceLine._meta.fields)
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

@admin.register(InvoicePayment)
class InvoicePaymentAdmin(admin.ModelAdmin):
    list_display = ("invoice", "method", "amount", "external_reference", "cashier", "created_at")
    readonly_fields = tuple(field.name for field in InvoicePayment._meta.fields)
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False
