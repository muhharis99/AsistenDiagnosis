from django.urls import path

from clinical.views import (
    ClinicalNoteCollectionView,
    DiagnosisCollectionView,
    EncounterCollectionView,
)

urlpatterns = [
    path("encounters/", EncounterCollectionView.as_view(), name="clinical-encounters"),
    path(
        "encounters/<uuid:encounter_id>/notes/",
        ClinicalNoteCollectionView.as_view(),
        name="clinical-notes",
    ),
    path(
        "encounters/<uuid:encounter_id>/diagnoses/",
        DiagnosisCollectionView.as_view(),
        name="clinical-diagnoses",
    ),
]
