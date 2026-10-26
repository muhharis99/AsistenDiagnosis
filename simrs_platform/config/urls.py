from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def health(_request):
    return Response({"status": "ok", "mode": "demo", "patient_data": "synthetic-only"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="api-docs"),
    path("api/mpi/", include("mpi.urls")),
    path("api/frontoffice/", include("frontoffice.urls")),
    path("api/cashier/", include("cashier.urls")),
    path("api/clinical/", include("clinical.urls")),
    path("api/orders/", include("orders.urls")),
    path("api/pharmacy/", include("pharmacy.urls")),
    path("api/diagnostics/", include("diagnostics.urls")),
    path("api/adt/", include("adt.urls")),
]
