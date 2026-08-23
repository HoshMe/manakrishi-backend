import random
import requests
from datetime import timedelta
from django.db.models import Count
from django.utils import timezone
from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

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

    if settings.DEBUG:
        return Response({'message': f'DEV: OTP is {otp_code}', 'debug_otp': otp_code})
    return Response({'error': 'SMS not configured'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


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
    token = serializer.validated_data.get('access_token') or serializer.validated_data.get('id_token', '')

    google_data = None
    if token.startswith('ey'):
        resp = requests.get(f'https://oauth2.googleapis.com/tokeninfo?id_token={token}')
        if resp.status_code == 200:
            google_data = resp.json()

    if not google_data:
        resp = requests.get(
            'https://www.googleapis.com/userinfo/v2/me',
            headers={'Authorization': f'Bearer {token}'}
        )
        if resp.status_code == 200:
            google_data = resp.json()

    if not google_data:
        return Response({'error': 'Invalid Google token'}, status=status.HTTP_400_BAD_REQUEST)

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
        state=data.get('state', ''),
        district=data.get('district', ''),
        services=data.get('services', []),
    )
    if data.get('password'):
        user.set_password(data['password'])
        user.login_methods = ['password']
        user.save()

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
    """List all operators - filterable by district. Returns machine_count too."""
    from .models import Machine
    from django.db.models import Count
    qs = User.objects.filter(role='operator')
    district = request.GET.get('district', '')
    state = request.GET.get('state', '')
    if district:
        qs = qs.filter(district__iexact=district)
    elif request.user.role not in ('admin',) and request.user.district:
        qs = qs.filter(district__iexact=request.user.district)
    if state:
        qs = qs.filter(state__iexact=state)
    # Annotate machine count
    qs = qs.annotate(machine_count=Count('machines', filter=DQ(machines__is_active=True)))
    operators = qs.values(
        'id', 'first_name', 'last_name', 'phone', 'address',
        'district', 'state', 'is_active', 'is_on_duty', 'services', 'machine_count', 'is_verified'
    )
    return Response(list(operators))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dealer_farmers(request):
    """List farmers associated with this dealer"""
    from bookings.models import Booking
    farmer_ids = Booking.objects.filter(dealer=request.user).values_list('farmer_id', flat=True).distinct()
    farmers = User.objects.filter(id__in=farmer_ids).values('id', 'first_name', 'last_name', 'phone', 'address')
    return Response(list(farmers))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def nearby_farmers(request):
    """List farmers in the same district — for manager and dealer roles"""
    if request.user.role not in ('manager', 'admin', 'dealer', 'operator'):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
    district = request.GET.get('district', '') or request.user.district
    if not district:
        return Response({'error': 'No district set on your profile'}, status=status.HTTP_400_BAD_REQUEST)
    farmers = User.objects.filter(role='farmer', district__iexact=district).values(
        'id', 'first_name', 'last_name', 'phone', 'address', 'district', 'state', 'is_verified', 'created_at'
    ).order_by('-created_at')
    return Response({'district': district, 'count': farmers.count(), 'results': list(farmers)})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_all_users(request):
    """List all users - manager only. Supports ?role= filter"""
    if request.user.role not in ('manager', 'admin'):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
    
    role = request.GET.get('role', '')
    qs = User.objects.all()
    if role:
        qs = qs.filter(role=role)
    
    users = qs.values('id', 'first_name', 'last_name', 'phone', 'email', 'role', 'address', 'is_verified', 'is_active', 'created_at').order_by('-created_at')
    return Response(list(users))


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def documents(request):
    """List or upload operator KYC documents"""
    from .models import KYCDocument

    if request.method == 'GET':
        docs = KYCDocument.objects.filter(user=request.user)
        data = [{
            'id': d.id,
            'doc_type': d.doc_type,
            'doc_number': d.doc_number,
            'doc_image': request.build_absolute_uri(d.doc_image.url) if d.doc_image else None,
            'status': d.status,
            'remarks': d.remarks,
            'uploaded_at': d.uploaded_at.strftime('%d %b %Y'),
        } for d in docs]
        kyc_status = 'verified' if docs.filter(status='approved').count() >= 2 else (
            'pending' if docs.filter(status='pending').exists() else 'not_submitted'
        )
        return Response({'documents': data, 'kyc_status': kyc_status})

    # POST - upload document
    doc_type = request.data.get('doc_type')  # 'aadhaar' or 'pan'
    doc_number = request.data.get('doc_number', '')
    doc_image = request.FILES.get('doc_image')

    if not doc_type or doc_type not in ('aadhaar', 'pan', 'driving_license'):
        return Response({'error': 'doc_type must be aadhaar, pan, or driving_license'}, status=status.HTTP_400_BAD_REQUEST)
    if not doc_image:
        return Response({'error': 'doc_image is required'}, status=status.HTTP_400_BAD_REQUEST)

    doc, created = KYCDocument.objects.update_or_create(
        user=request.user, doc_type=doc_type,
        defaults={'doc_number': doc_number, 'doc_image': doc_image, 'status': 'pending', 'remarks': ''}
    )
    return Response({'status': 'uploaded', 'doc_type': doc_type, 'id': doc.id}, status=status.HTTP_201_CREATED)




@api_view(['GET'])
@permission_classes([IsAuthenticated])
def kyc_pending(request):
    """List users with pending KYC - admin only"""
    if request.user.role not in ('manager', 'admin'):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
    from .models import KYCDocument
    from django.db.models import Prefetch
    users_with_pending = User.objects.filter(
        kyc_documents__status='pending'
    ).distinct().prefetch_related(
        Prefetch('kyc_documents', queryset=KYCDocument.objects.all(), to_attr='all_docs')
    )
    data = []
    for user in users_with_pending:
        docs = {d.doc_type: d for d in user.all_docs}
        entry = {
            'user_id': user.id,
            'user_name': user.get_full_name(),
            'user_phone': user.phone,
            'kyc_status': 'verified' if all(d.status == 'approved' for d in docs.values()) and len(docs) >= 2 else (
                'pending' if any(d.status == 'pending' for d in docs.values()) else 'rejected'
            ),
        }
        for doc_type, d in docs.items():
            entry[doc_type] = {
                'id': d.id,
                'doc_number': d.doc_number,
                'doc_image': request.build_absolute_uri(d.doc_image.url) if d.doc_image else None,
                'status': d.status,
                'remarks': d.remarks,
                'uploaded_at': d.uploaded_at.strftime('%d %b %Y'),
            }
        data.append(entry)
    return Response(data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def kyc_review(request):
    """Approve or reject all KYC documents for a user - admin only"""
    if request.user.role not in ('manager', 'admin'):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
    from .models import KYCDocument
    user_id = request.data.get('user_id')
    action = request.data.get('action')  # 'approve' or 'reject'
    remarks = request.data.get('remarks', '')
    if not user_id or action not in ('approve', 'reject'):
        return Response({'error': 'user_id and action (approve/reject) required'}, status=status.HTTP_400_BAD_REQUEST)
    docs = KYCDocument.objects.filter(user_id=user_id)
    if not docs.exists():
        return Response({'error': 'No documents found'}, status=status.HTTP_404_NOT_FOUND)
    docs.update(status='approved' if action == 'approve' else 'rejected', remarks=remarks)
    user = User.objects.get(id=user_id)
    user.is_verified = action == 'approve'
    user.save()
    return Response({'status': 'approved' if action == 'approve' else 'rejected', 'user_verified': user.is_verified})

# ─── Training Applications ───────────────────────────────────────────────────

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def training_applications(request):
    """Operator: list own applications or submit new one"""
    from .models import TrainingApplication
    if request.method == 'GET':
        apps = TrainingApplication.objects.filter(user=request.user)
        data = [{
            'id': a.id,
            'training_type': a.training_type,
            'training_label': a.get_training_type_display(),
            'preferred_date': a.preferred_date.strftime('%d %b %Y') if a.preferred_date else None,
            'preferred_location': a.preferred_location,
            'experience_years': a.experience_years,
            'notes': a.notes,
            'status': a.status,
            'remarks': a.remarks,
            'applied_at': a.applied_at.strftime('%d %b %Y'),
        } for a in apps]
        return Response(data)

    training_type = request.data.get('training_type')
    valid_types = [c[0] for c in TrainingApplication.TRAINING_TYPE_CHOICES]
    if not training_type or training_type not in valid_types:
        return Response({'error': f'training_type must be one of: {valid_types}'}, status=status.HTTP_400_BAD_REQUEST)

    existing = TrainingApplication.objects.filter(user=request.user, training_type=training_type, status__in=['pending', 'approved']).first()
    if existing:
        return Response({'error': 'You already have an active application for this training type.'}, status=status.HTTP_400_BAD_REQUEST)

    from datetime import date
    preferred_date_str = request.data.get('preferred_date', '')
    preferred_date = None
    if preferred_date_str:
        try:
            preferred_date = date.fromisoformat(preferred_date_str)
        except ValueError:
            return Response({'error': 'preferred_date must be YYYY-MM-DD'}, status=status.HTTP_400_BAD_REQUEST)

    app = TrainingApplication.objects.create(
        user=request.user,
        training_type=training_type,
        preferred_date=preferred_date,
        preferred_location=request.data.get('preferred_location', ''),
        experience_years=int(request.data.get('experience_years', 0) or 0),
        notes=request.data.get('notes', ''),
    )
    return Response({'status': 'applied', 'id': app.id, 'training_type': app.training_type}, status=status.HTTP_201_CREATED)


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def training_admin(request):
    """Admin/manager: list all applications or review one"""
    if request.user.role not in ('manager', 'admin'):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
    from .models import TrainingApplication

    if request.method == 'GET':
        status_filter = request.GET.get('status', '')
        qs = TrainingApplication.objects.select_related('user').all()
        if status_filter:
            qs = qs.filter(status=status_filter)
        data = [{
            'id': a.id,
            'user_id': a.user_id,
            'user_name': a.user.get_full_name(),
            'user_phone': a.user.phone,
            'training_type': a.training_type,
            'training_label': a.get_training_type_display(),
            'preferred_date': a.preferred_date.strftime('%d %b %Y') if a.preferred_date else None,
            'preferred_location': a.preferred_location,
            'experience_years': a.experience_years,
            'notes': a.notes,
            'status': a.status,
            'remarks': a.remarks,
            'applied_at': a.applied_at.strftime('%d %b %Y'),
        } for a in qs]
        return Response(data)

    app_id = request.data.get('id')
    action = request.data.get('action')
    if not app_id or action not in ('approve', 'reject', 'complete'):
        return Response({'error': 'id and action (approve/reject/complete) required'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        app = TrainingApplication.objects.get(id=app_id)
    except TrainingApplication.DoesNotExist:
        return Response({'error': 'Not found'}, status=status.HTTP_404_NOT_FOUND)
    status_map = {'approve': 'approved', 'reject': 'rejected', 'complete': 'completed'}
    app.status = status_map[action]
    app.remarks = request.data.get('remarks', '')
    from django.utils import timezone
    app.reviewed_at = timezone.now()
    app.save()
    return Response({'status': app.status})


@api_view(['GET', 'POST', 'DELETE'])
@permission_classes([IsAuthenticated])
def machines(request):
    """Operator: list/add/delete own machines"""
    from .models import Machine
    if request.method == 'GET':
        target_id = request.GET.get('operator_id')
        if target_id and request.user.role in ('manager', 'admin'):
            qs = Machine.objects.filter(operator_id=target_id)
        else:
            qs = Machine.objects.filter(operator=request.user)
        from .serializers import MachineSerializer
        return Response(MachineSerializer(qs, many=True).data)

    if request.method == 'POST':
        machine_type = request.data.get('machine_type', '')
        valid = [c[0] for c in Machine.MACHINE_TYPE_CHOICES]
        if machine_type not in valid:
            return Response({'error': f'machine_type must be one of: {valid}'}, status=status.HTTP_400_BAD_REQUEST)
        machine = Machine.objects.create(
            operator=request.user,
            machine_type=machine_type,
            model_name=request.data.get('model_name', ''),
            registration_number=request.data.get('registration_number', ''),
        )
        from .serializers import MachineSerializer
        return Response(MachineSerializer(machine).data, status=status.HTTP_201_CREATED)

    if request.method == 'DELETE':
        machine_id = request.data.get('id')
        Machine.objects.filter(id=machine_id, operator=request.user).delete()
        return Response({'status': 'deleted'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def machine_stats(request):
    """Admin/manager: machine counts grouped by state → district → type"""
    if request.user.role not in ('manager', 'admin'):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
    from .models import Machine
    from django.db.models import Count

    qs = Machine.objects.filter(is_active=True).select_related('operator')
    # Scope to manager's district
    if request.user.role == 'manager' and request.user.district:
        qs = qs.filter(operator__district__iexact=request.user.district)

    # Build state → district → machine_type → count
    result = {}
    for m in qs:
        state = m.operator.state or 'Unknown State'
        district = m.operator.district or 'Unknown District'
        mtype = m.get_machine_type_display()
        result.setdefault(state, {}).setdefault(district, {}).setdefault(mtype, 0)
        result[state][district][mtype] += 1

    # Also compute totals per district
    output = []
    for state, districts in sorted(result.items()):
        state_entry = {'state': state, 'districts': []}
        for district, types in sorted(districts.items()):
            total = sum(types.values())
            state_entry['districts'].append({
                'district': district,
                'total_machines': total,
                'by_type': [{'type': t, 'count': c} for t, c in sorted(types.items())],
            })
        output.append(state_entry)
    return Response(output)


from django.db import models as django_models
from django.db.models import Q as DQ


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_operator_district(request):
    """Admin/manager: update an operator's assigned district and state."""
    if request.user.role not in ('manager', 'admin'):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
    operator_id = request.data.get('operator_id')
    new_district = request.data.get('district', '').strip()
    new_state = request.data.get('state', '').strip()
    if not operator_id or not new_district:
        return Response({'error': 'operator_id and district are required'}, status=status.HTTP_400_BAD_REQUEST)
    op = User.objects.filter(id=operator_id, role='operator').first()
    if not op:
        return Response({'error': 'Operator not found'}, status=status.HTTP_404_NOT_FOUND)
    op.district = new_district
    if new_state:
        op.state = new_state
    op.save()
    return Response({'status': 'updated', 'operator_id': operator_id, 'district': op.district, 'state': op.state})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def license_requests(request):
    """Admin/manager: list operators who need license assistance"""
    if request.user.role not in ('manager', 'admin'):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
    operators = User.objects.filter(role='operator', needs_license=True).values(
        'id', 'first_name', 'last_name', 'phone', 'district', 'state', 'services', 'is_verified'
    )
    return Response(list(operators))


# ─── Password Login ───────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def login_password(request):
    phone = request.data.get('phone', '').strip()
    password = request.data.get('password', '')

    if not phone or not password:
        return Response({'error': 'Phone and password required'}, status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.filter(phone=phone).first()
    if not user:
        return Response({'error': 'User not found. Please sign up first.'}, status=status.HTTP_404_NOT_FOUND)

    if not user.check_password(password):
        return Response({'error': 'Incorrect password'}, status=status.HTTP_401_UNAUTHORIZED)

    tokens = get_tokens_for_user(user)
    return Response({'tokens': tokens, 'user': UserSerializer(user).data})


# ─── Toggle Duty ──────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def toggle_duty(request):
    user = request.user
    user.is_on_duty = not user.is_on_duty
    user.save()
    return Response({'is_on_duty': user.is_on_duty})


# ─── Biometric Login ─────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def enable_biometric(request):
    import secrets
    from django.utils import timezone

    device_id = request.data.get('device_id', '').strip()
    device_name = request.data.get('device_name', 'Unknown Device')

    if not device_id:
        return Response({'error': 'device_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    token = secrets.token_urlsafe(32)
    user = request.user

    devices = [d for d in (user.biometric_devices or []) if d.get('device_id') != device_id]
    devices.append({
        'device_id': device_id,
        'token': token,
        'device_name': device_name,
        'created_at': timezone.now().isoformat(),
    })
    user.biometric_devices = devices
    if 'biometric' not in user.login_methods:
        user.login_methods = list(set(user.login_methods + ['biometric']))
    user.save()
    return Response({'biometric_token': token, 'login_methods': user.login_methods})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def disable_biometric(request):
    device_id = request.data.get('device_id', '').strip()
    user = request.user

    if device_id:
        user.biometric_devices = [d for d in (user.biometric_devices or []) if d.get('device_id') != device_id]
    else:
        user.biometric_devices = []

    if not user.biometric_devices:
        user.login_methods = [m for m in user.login_methods if m != 'biometric']
    user.save()
    return Response({'login_methods': user.login_methods})


@api_view(['POST'])
@permission_classes([AllowAny])
def login_biometric(request):
    phone = request.data.get('phone', '').strip()
    biometric_token = request.data.get('biometric_token', '')
    device_id = request.data.get('device_id', '').strip()

    if not phone or not biometric_token or not device_id:
        return Response({'error': 'Phone, device_id, and biometric_token required'}, status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.filter(phone=phone).first()
    if not user:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)

    if 'biometric' not in user.login_methods:
        return Response({'error': 'Biometric login not enabled'}, status=status.HTTP_403_FORBIDDEN)

    valid = any(
        d.get('device_id') == device_id and d.get('token') == biometric_token
        for d in (user.biometric_devices or [])
    )
    if not valid:
        return Response({'error': 'Invalid biometric credentials'}, status=status.HTTP_401_UNAUTHORIZED)

    tokens = get_tokens_for_user(user)
    return Response({'tokens': tokens, 'user': UserSerializer(user).data})


# ─── Admin Login (superuser only) ────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def admin_login(request):
    phone = request.data.get('phone', '').strip()
    password = request.data.get('password', '')

    if not phone or not password:
        return Response({'error': 'Phone and password required'}, status=status.HTTP_400_BAD_REQUEST)

    user = User.objects.filter(phone=phone).first()
    if not user or not user.is_superuser or not user.check_password(password):
        return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

    tokens = get_tokens_for_user(user)
    return Response({'tokens': tokens, 'user': UserSerializer(user).data})
