from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

urlpatterns = [
    path('send-otp/', views.send_otp),
    path('verify-otp/', views.verify_otp),
    path('verify-otp-only/', views.verify_otp_only),
    path('login/', views.login_password),
    path('login/biometric/', views.login_biometric),
    path('google-login/', views.google_login),
    path('signup/', views.signup),
    path('profile/', views.profile),
    path('push-token/', views.update_push_token),
    path('toggle-duty/', views.toggle_duty),
    path('biometric/enable/', views.enable_biometric),
    path('biometric/disable/', views.disable_biometric),
    path('token/refresh/', TokenRefreshView.as_view()),
    path('addresses/', views.addresses),
    path('addresses/<int:pk>/', views.delete_address),
    path('delete-account/', views.delete_account),
    path('operators/', views.list_operators),
    path('dealer-farmers/', views.dealer_farmers),
    path('all-users/', views.list_all_users),
    path('documents/', views.documents),
    path('kyc/review/', views.kyc_review),
    path('kyc/pending/', views.kyc_pending),
]
