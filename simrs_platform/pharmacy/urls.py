from django.urls import path

from pharmacy.views import MedicationDispenseCollectionView

urlpatterns = [
    path(
        "orders/<uuid:order_id>/dispenses/",
        MedicationDispenseCollectionView.as_view(),
        name="medication-dispenses",
    ),
]
