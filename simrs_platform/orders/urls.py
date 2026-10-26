from django.urls import path

from orders.views import ServiceOrderCancelView, ServiceOrderCollectionView

urlpatterns = [
    path("orders/", ServiceOrderCollectionView.as_view(), name="service-orders"),
    path(
        "orders/<uuid:order_id>/cancel/",
        ServiceOrderCancelView.as_view(),
        name="service-order-cancel",
    ),
]
