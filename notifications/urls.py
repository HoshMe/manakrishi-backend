from django.urls import path
from . import views

urlpatterns = [
    path('', views.list_notifications),
    path('mark-read/', views.mark_read),
    path('unread-count/', views.unread_count),
    path('help/', views.help_faqs),
    path('test-push/', views.test_push),
]
