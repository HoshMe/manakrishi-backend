from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import BookingViewSet, rate_booking, crops_list, service_info, check_operators, accept_booking, reject_booking, dealer_stats

router = DefaultRouter()
router.register('', BookingViewSet, basename='booking')

urlpatterns = [
    path('crops/', crops_list),
    path('service-info/', service_info),
    path('check-operators/', check_operators),
    path('rate/', rate_booking),
    path('accept/', accept_booking),
    path('reject/', reject_booking),
    path('dealer-stats/', dealer_stats),
    path('', include(router.urls)),
]
