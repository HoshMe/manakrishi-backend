from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import BookingViewSet, rate_booking, crops_list, service_info, accept_booking, reject_booking

router = DefaultRouter()
router.register('', BookingViewSet, basename='booking')

urlpatterns = [
    path('crops/', crops_list),
    path('service-info/', service_info),
    path('rate/', rate_booking),
    path('accept/', accept_booking),
    path('reject/', reject_booking),
    path('', include(router.urls)),
]
