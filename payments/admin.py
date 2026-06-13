from django.contrib import admin
from .models import Payment, Commission


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['razorpay_order_id', 'user', 'booking', 'amount', 'status', 'created_at']
    list_filter = ['status']


@admin.register(Commission)
class CommissionAdmin(admin.ModelAdmin):
    list_display = ['dealer', 'booking', 'amount', 'is_withdrawn', 'created_at']
    list_filter = ['is_withdrawn']
