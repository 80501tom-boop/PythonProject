from django.urls import path

from . import views


urlpatterns = [

    path(
        "",
        views.index,
        name="index"
    ),

    path(
        "add-stock/",
        views.add_stock,
        name="add_stock"
    ),

    path(
        "stock/<str:symbol>/",
        views.stock_detail,
        name="stock_detail"
    ),

]