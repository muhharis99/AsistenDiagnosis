from django.urls import path

from diagnostics.views import DiagnosticResultCollectionView

urlpatterns = [
    path(
        "orders/<uuid:order_id>/results/",
        DiagnosticResultCollectionView.as_view(),
        name="diagnostic-results",
    ),
]
