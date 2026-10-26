from django.urls import path

from cashier.views import (
    InvoiceCollectionView,
    InvoiceIssueView,
    InvoicePaymentView,
    TariffCollectionView,
)

urlpatterns = [
    path("tariffs/", TariffCollectionView.as_view(), name="tariffs"),
    path("invoices/", InvoiceCollectionView.as_view(), name="invoices"),
    path("invoices/<uuid:invoice_id>/issue/", InvoiceIssueView.as_view(), name="invoice-issue"),
    path(
        "invoices/<uuid:invoice_id>/payments/",
        InvoicePaymentView.as_view(),
        name="invoice-payments",
    ),
]
