from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    BookingViewSet, rate_booking, crops_list, service_info, check_operators,
    accept_booking, reject_booking, dealer_stats, service_pricing, update_user_role,
    track_booking, set_booking_price, commission_rules, operators_for_booking, admin_assign_operator,
    admin_create_booking, admin_update_booking,
)

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
    path('pricing/', service_pricing),
    path('update-user-role/', update_user_role),
    path('commission-rules/', commission_rules),
    path('set-price/', set_booking_price),
    path('track/', track_booking),
    path('operators-for-booking/', operators_for_booking),
    path('admin-assign/', admin_assign_operator),
    path('admin-create/', admin_create_booking),
    path('admin-update/', admin_update_booking),
    path('', include(router.urls)),
]
