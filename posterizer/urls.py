from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("orders/", views.my_orders, name="my_orders"),
    path("orders/<int:pk>/image/<str:kind>/", views.order_image, name="order_image"),
    path("orders/<int:pk>/stl/", views.order_stl, name="order_stl"),
    path("api/config", views.get_config, name="get_config"),
    path("api/process", views.process, name="process"),
    path("api/orders/create", views.order_create, name="order_create"),
]
