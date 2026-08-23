from django.contrib import admin
from .models import User, OTP, Machine


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ['phone', 'email', 'first_name', 'role', 'is_verified', 'created_at']
    list_filter = ['role', 'is_verified']
    search_fields = ['phone', 'email', 'first_name', 'last_name']


@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = ['phone', 'otp', 'is_used', 'created_at', 'expires_at']
    list_filter = ['is_used']


@admin.register(Machine)
class MachineAdmin(admin.ModelAdmin):
    list_display = ['operator', 'machine_type', 'model_name', 'registration_number', 'is_active', 'created_at']
    list_filter = ['machine_type', 'is_active', 'operator__district', 'operator__state']
    search_fields = ['operator__phone', 'operator__first_name', 'model_name', 'registration_number']
    raw_id_fields = ['operator']
