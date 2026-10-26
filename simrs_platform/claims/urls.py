from django.urls import path

from claims.views import ClaimAdjudicationView, ClaimCollectionReceiptView, ClaimCollectionView, ClaimSubmitView, ReceivableSummaryView

urlpatterns = [
    path("claims/", ClaimCollectionView.as_view(), name="claims"),
    path("claims/<uuid:claim_id>/submit/", ClaimSubmitView.as_view(), name="claim-submit"),
    path("claims/<uuid:claim_id>/adjudicate/", ClaimAdjudicationView.as_view(), name="claim-adjudicate"),
    path(
        "claims/<uuid:claim_id>/<str:collection_type>/",
        ClaimCollectionReceiptView.as_view(),
        name="claim-collections",
    ),
    path("receivables/", ReceivableSummaryView.as_view(), name="receivables"),
]
