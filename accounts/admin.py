from django.contrib import admin
from .models import User, OTP


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['phone', 'email', 'first_name', 'role', 'is_verified', 'created_at']
    list_filter = ['role', 'is_verified']
    search_fields = ['phone', 'email', 'first_name', 'last_name']


@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = ['phone', 'otp', 'is_used', 'created_at', 'expires_at']
    list_filter = ['is_used']
