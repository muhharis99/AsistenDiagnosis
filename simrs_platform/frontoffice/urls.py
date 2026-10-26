from django.urls import path
from frontoffice.views import ArriveRegistrationView, QueueActionView, QueueCollectionView, RegistrationCollectionView

urlpatterns = [
    path("registrations/", RegistrationCollectionView.as_view(), name="registrations"),
    path("registrations/<uuid:registration_id>/arrive/", ArriveRegistrationView.as_view(), name="registration-arrive"),
    path("queue/", QueueCollectionView.as_view(), name="queue-list"),
    path("queue/<uuid:ticket_id>/<str:action>/", QueueActionView.as_view(), name="queue-action"),
]
