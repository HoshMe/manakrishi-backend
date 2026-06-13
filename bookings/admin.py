from django.contrib import admin
from .models import Booking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['booking_id', 'service', 'farmer', 'operator', 'status', 'amount', 'scheduled_date']
    list_filter = ['status', 'service', 'scheduled_date']
    search_fields = ['booking_id', 'farmer__phone', 'farmer__first_name']
    readonly_fields = ['booking_id']


from .models import Crop

@admin.register(Crop)
class CropAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'order']
    list_editable = ['is_active', 'order']
    search_fields = ['name']
