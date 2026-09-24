from django.urls import path
from . import views


urlpatterns = [
    path("", views.index, name="index"),

    path(
        "stock/<str:symbol>/",
        views.stock_detail,
        name="stock_detail"
    ),
]