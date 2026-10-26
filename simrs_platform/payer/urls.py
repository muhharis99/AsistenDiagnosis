from django.urls import path

from payer.views import (
    CoverageCollectionView,
    PayerCollectionView,
    PlanCollectionView,
    RegistrationCoverageCollectionView,
)

urlpatterns = [
    path("payers/", PayerCollectionView.as_view(), name="payer-organizations"),
    path("plans/", PlanCollectionView.as_view(), name="payer-plans"),
    path("coverages/", CoverageCollectionView.as_view(), name="payer-coverages"),
    path(
        "registration-coverages/",
        RegistrationCoverageCollectionView.as_view(),
        name="registration-coverages",
    ),
]
