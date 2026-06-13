from django.urls import path
from . import views

urlpatterns = [
    path('create-order/', views.create_order),
    path('verify/', views.verify_payment),
    path('webhook/', views.razorpay_webhook),
    path('transactions/', views.list_transactions),
    path('commissions/', views.list_commissions),
    path('wallet/', views.wallet),
    path('earnings/', views.earnings),
    path('withdraw/', views.withdraw_commission),
    path('invoice/<str:booking_id>/', views.generate_invoice),
]
