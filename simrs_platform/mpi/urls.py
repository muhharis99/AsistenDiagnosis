from django.urls import path

from mpi.views import PatientCollectionView, PatientDetailView

urlpatterns = [
    path("patients/", PatientCollectionView.as_view(), name="mpi-patients"),
    path("patients/<uuid:patient_id>/", PatientDetailView.as_view(), name="mpi-patient-detail"),
]
