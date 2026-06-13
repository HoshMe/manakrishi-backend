import random
import requests
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
import boto3

from .models import User, OTP
from .serializers import (
    UserSerializer, SignupSerializer, SendOtpSerializer,
    VerifyOtpSerializer, GoogleLoginSerializer,
)


def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    refresh['role'] = user.role
    return {'access': str(refresh.access_token), 'refresh': str(refresh)}


# ─── SMS OTP via AWS End User Messaging ───────────────────────────────────────

from rest_framework.throttling import AnonRateThrottle

class OtpThrottle(AnonRateThrottle):
    rate = '5/minute'

@api_view(['POST'])
@permission_classes([AllowAny])
def send_otp(request):
    # Apply OTP throttle
    throttle = OtpThrottle()
    if not throttle.allow_request(request, None):
        return Response({'error': 'Too many OTP requests. Please wait.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)

    serializer = SendOtpSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    phone = serializer.validated_data['phone']

    otp_code = str(random.randint(100000, 999999))
    expires_at = timezone.now() + timedelta(minutes=5)

    # Store OTP
    OTP.objects.filter(phone=phone, is_used=False).update(is_used=True)
    OTP.objects.create(phone=phone, otp=otp_code, expires_at=expires_at)

    # Send via AWS
    try:
        client = boto3.client(
            'pinpoint-sms-voice-v2',
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )
        client.send_text_message(
            DestinationPhoneNumber=phone,
            OriginationIdentity=settings.AWS_SMS_ORIGINATION_ID,
            MessageBody=f'Your ManaKrishi OTP is: {otp_code}. Valid for 5 minutes.',
            MessageType='TRANSACTIONAL',
        )
    except Exception as e:
        if settings.DEBUG:
            return Response({'message': f'DEV: OTP is {otp_code}', 'debug_otp': otp_code})
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return Response({'message': 'OTP sent successfully'})


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_otp(request):
    serializer = VerifyOtpSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    phone = serializer.validated_data['phone']
    otp_code = serializer.validated_data['otp']

    otp_obj = OTP.objects.filter(
        phone=phone, otp=otp_code, is_used=False, expires_at__gt=timezone.now()
    ).first()

    if not otp_obj:
        return Response({'error': 'Invalid or expired OTP'}, status=status.HTTP_400_BAD_REQUEST)

    otp_obj.is_used = True
    otp_obj.save()

    # Login: find user by phone
    user = User.objects.filter(phone=phone).first()
    if not user:
        return Response({'error': 'User not found. Please sign up first.'}, status=status.HTTP_404_NOT_FOUND)

    user.is_verified = True
    user.save()

    tokens = get_tokens_for_user(user)
    return Response({'tokens': tokens, 'user': UserSerializer(user).data})


# ─── Google OAuth Login ───────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def google_login(request):
    serializer = GoogleLoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    access_token = serializer.validated_data['access_token']

    # Fetch user info from Google
    resp = requests.get(
        'https://www.googleapis.com/userinfo/v2/me',
        headers={'Authorization': f'Bearer {access_token}'}
    )
    if resp.status_code != 200:
        return Response({'error': 'Invalid Google token'}, status=status.HTTP_400_BAD_REQUEST)

    google_data = resp.json()
    email = google_data.get('email', '').lower()

    user = User.objects.filter(email=email).first()
    if not user:
        return Response({'error': 'User not found. Please sign up first.'}, status=status.HTTP_404_NOT_FOUND)

    tokens = get_tokens_for_user(user)
    return Response({'tokens': tokens, 'user': UserSerializer(user).data})


# ─── Signup ───────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def signup(request):
    serializer = SignupSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    # Check existing
    if data.get('phone') and User.objects.filter(phone=data['phone']).exists():
        return Response({'error': 'Phone already registered'}, status=status.HTTP_400_BAD_REQUEST)
    email = (data.get('email') or '').strip().lower()
    if email and User.objects.filter(email=email).exists():
        return Response({'error': 'Email already registered'}, status=status.HTTP_400_BAD_REQUEST)

    name_parts = data['name'].split(' ', 1)
    user = User.objects.create_user(
        username=data.get('phone') or email or str(data['name']),
        phone=data.get('phone') or None,
        email=email,
        first_name=name_parts[0],
        last_name=name_parts[1] if len(name_parts) > 1 else '',
        role=data['role'],
    )

    tokens = get_tokens_for_user(user)
    return Response({'tokens': tokens, 'user': UserSerializer(user).data}, status=status.HTTP_201_CREATED)


# ─── Profile ─────────────────────────────────────────────────────────────────

@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def profile(request):
    if request.method == 'GET':
        return Response(UserSerializer(request.user).data)

    serializer = UserSerializer(request.user, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_push_token(request):
    token = request.data.get('push_token')
    if token:
        request.user.push_token = token
        request.user.save()
    return Response({'status': 'ok'})


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_otp_only(request):
    """Verify OTP without login - used during signup to confirm phone ownership"""
    serializer = VerifyOtpSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    phone = serializer.validated_data['phone']
    otp_code = serializer.validated_data['otp']

    otp_obj = OTP.objects.filter(
        phone=phone, otp=otp_code, is_used=False, expires_at__gt=timezone.now()
    ).first()

    if not otp_obj:
        return Response({'error': 'Invalid or expired OTP'}, status=status.HTTP_400_BAD_REQUEST)

    otp_obj.is_used = True
    otp_obj.save()
    return Response({'verified': True})


# ─── Addresses ────────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def addresses(request):
    from django.http import JsonResponse
    if request.method == 'GET':
        # Return user's saved addresses (stored as JSON in a simple model)
        addrs = request.user.saved_addresses.all().values('id', 'address')
        return Response(list(addrs))
    
    address_text = request.data.get('address', '')
    if not address_text:
        return Response({'error': 'Address is required'}, status=status.HTTP_400_BAD_REQUEST)
    request.user.saved_addresses.create(address=address_text)
    return Response({'status': 'ok'}, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_address(request, pk):
    request.user.saved_addresses.filter(id=pk).delete()
    return Response({'status': 'ok'})


# ─── Delete Account ───────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def delete_account(request):
    user = request.user
    user.is_active = False
    user.save()
    return Response({'status': 'Account deactivated'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_operators(request):
    """List all operators (for area managers)"""
    operators = User.objects.filter(role='operator').values('id', 'first_name', 'last_name', 'phone', 'address', 'is_active')
    return Response(list(operators))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dealer_farmers(request):
    """List farmers associated with this dealer"""
    # Farmers who have bookings created by this dealer
    from bookings.models import Booking
    farmer_ids = Booking.objects.filter(dealer=request.user).values_list('farmer_id', flat=True).distinct()
    farmers = User.objects.filter(id__in=farmer_ids).values('id', 'first_name', 'last_name', 'phone', 'address')
    return Response(list(farmers))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_all_users(request):
    """List all users - admin only. Supports ?role= filter"""
    if request.user.role not in ('admin', 'manager'):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
    
    role = request.GET.get('role', '')
    qs = User.objects.all()
    if role:
        qs = qs.filter(role=role)
    
    users = qs.values('id', 'first_name', 'last_name', 'phone', 'email', 'role', 'address', 'is_verified', 'is_active', 'created_at').order_by('-created_at')
    return Response(list(users))


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def documents(request):
    """List or upload operator documents"""
    if request.method == 'GET':
        # Return placeholder - in production, query a Document model
        return Response([])
    
    # POST - upload document (placeholder)
    return Response({'status': 'ok', 'message': 'Document uploaded'}, status=status.HTTP_201_CREATED)
