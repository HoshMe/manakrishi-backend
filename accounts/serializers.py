from rest_framework import serializers
from .models import User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'phone', 'email', 'first_name', 'last_name', 'role', 'language', 'address', 'state', 'district', 'services', 'login_methods', 'is_on_duty', 'location_lat', 'location_lng', 'is_verified', 'push_token']
        read_only_fields = ['id', 'is_verified']


class SignupSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    phone = serializers.CharField(max_length=15, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    password = serializers.CharField(max_length=128, required=False, allow_blank=True)
    role = serializers.ChoiceField(choices=['farmer', 'operator', 'dealer', 'admin'])
    state = serializers.CharField(max_length=50, required=False, allow_blank=True)
    district = serializers.CharField(max_length=50, required=False, allow_blank=True)
    services = serializers.ListField(child=serializers.CharField(), required=False, default=list)


class SendOtpSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=15)


class VerifyOtpSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=15)
    otp = serializers.CharField(max_length=6)


class GoogleLoginSerializer(serializers.Serializer):
    access_token = serializers.CharField(required=False, allow_blank=True, default='')
    id_token = serializers.CharField(required=False, allow_blank=True, default='')
