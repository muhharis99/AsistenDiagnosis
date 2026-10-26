from django.urls import path

from adt.views import AdmissionCollectionView, AdmissionDischargeView

urlpatterns = [
    path("admissions/", AdmissionCollectionView.as_view(), name="adt-admissions"),
    path(
        "admissions/<uuid:admission_id>/discharge/",
        AdmissionDischargeView.as_view(),
        name="adt-discharge",
    ),
]
