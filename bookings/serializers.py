from rest_framework import serializers
from .models import Booking
from accounts.serializers import UserSerializer


class BookingSerializer(serializers.ModelSerializer):
    farmer_detail = UserSerializer(source='farmer', read_only=True)
    operator_detail = UserSerializer(source='operator', read_only=True)

    class Meta:
        model = Booking
        fields = '__all__'
        read_only_fields = ['booking_id', 'farmer', 'operator', 'commission_amount', 'completed_at']


class CreateBookingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Booking
        fields = ['service', 'crop', 'area_acres', 'scheduled_date', 'scheduled_time',
                  'location_address', 'location_lat', 'location_lng', 'field_photo', 'spray_type',
                  'delivery_address', 'invoice_address']
