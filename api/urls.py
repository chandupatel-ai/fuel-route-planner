from django.urls import path
from .views import RoutePlannerView, FuelStopsListView

urlpatterns = [
    path('route/', RoutePlannerView.as_view(), name='route-planner'),
    path('fuel-stops/', FuelStopsListView.as_view(), name='fuel-stops-list'),
]