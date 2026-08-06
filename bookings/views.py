from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny

from accounts.models import User
from .models import Booking
from .serializers import BookingSerializer, CreateBookingSerializer
from notifications.tasks import send_booking_notification


class IsRole:
    """Mixin to check user role"""
    def check_role(self, request, allowed_roles):
        return request.user.role in allowed_roles or request.user.role == 'admin'


class BookingViewSet(viewsets.ModelViewSet, IsRole):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'booking_id'

    def get_queryset(self):
        user = self.request.user
        if user.role == 'farmer':
            qs = Booking.objects.filter(farmer=user)
        elif user.role == 'operator':
            if user.district:
                qs = Booking.objects.filter(
                    models.Q(operator=user) |
                    models.Q(status='pending', farmer__district__iexact=user.district)
                ).distinct()
            else:
                qs = Booking.objects.filter(operator=user)
        elif user.role == 'dealer':
            qs = Booking.objects.filter(dealer=user)
        elif user.role == 'manager':
            qs = Booking.objects.filter(farmer__district__iexact=user.district) if user.district else Booking.objects.all()
        elif user.role == 'admin':
            qs = Booking.objects.all()
        else:
            return Booking.objects.none()

        # Filter by status query param (supports comma-separated values e.g. ?status=confirmed,on_the_way)
        status_param = self.request.query_params.get('status', '').strip()
        if status_param:
            statuses = [s.strip() for s in status_param.split(',') if s.strip()]
            qs = qs.filter(status__in=statuses)
        return qs

    def get_serializer_class(self):
        if self.action == 'create':
            return CreateBookingSerializer
        return BookingSerializer

    def create(self, request, *args, **kwargs):
        print(f'BOOKING CREATE DATA: {request.data}')
        serializer = self.get_serializer(data=request.data)
        if not serializer.is_valid():
            print(f'BOOKING VALIDATION ERRORS: {serializer.errors}')
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        self.perform_create(serializer)
        # Return full booking data including amount and booking_id
        booking = Booking.objects.get(id=serializer.instance.id)
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        if self.request.user.role == 'dealer':
            farmer_id = self.request.data.get('farmer_id')
            farmer_phone = self.request.data.get('farmer_phone', '').strip()
            farmer_name = self.request.data.get('farmer_name', '').strip()
            farmer = None

            if farmer_id:
                farmer = User.objects.filter(id=farmer_id, role='farmer').first()
            elif farmer_phone:
                farmer = User.objects.filter(phone=farmer_phone).first()
                if not farmer:
                    name_parts = farmer_name.split(' ', 1)
                    farmer = User.objects.create_user(
                        username=farmer_phone,
                        phone=farmer_phone,
                        first_name=name_parts[0],
                        last_name=name_parts[1] if len(name_parts) > 1 else '',
                        role='farmer',
                    )
            elif farmer_name:
                # No phone — create a phoneless farmer record using name + dealer context
                import uuid
                name_parts = farmer_name.split(' ', 1)
                farmer = User.objects.create_user(
                    username=f'farmer_{uuid.uuid4().hex[:8]}',
                    first_name=name_parts[0],
                    last_name=name_parts[1] if len(name_parts) > 1 else '',
                    role='farmer',
                )

            if not farmer:
                from rest_framework.exceptions import ValidationError
                raise ValidationError({'farmer_name': 'Farmer name is required'})

            booking = serializer.save(
                farmer=farmer,
                dealer=self.request.user,
                status='pending',
                amount=0,
            )
        else:
            booking = serializer.save(farmer=self.request.user, status='pending', amount=0)

        # Dispatch to nearby operators
        from notifications.tasks import assign_booking_to_nearby_operators
        assign_booking_to_nearby_operators.delay(booking.id)
        send_booking_notification.delay(booking.id, 'booking_confirmed')

    @action(detail=True, methods=['post'])
    def assign_operator(self, request, pk=None):
        if not self.check_role(request, ['manager']):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        booking = self.get_object()
        operator_id = request.data.get('operator_id')
        booking.operator_id = operator_id
        booking.status = 'operator_assigned'
        booking.save()
        send_booking_notification.delay(booking.id, 'operator_assigned')
        return Response(BookingSerializer(booking).data)

    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        booking = self.get_object()
        new_status = request.data.get('status')
        valid = ['on_the_way', 'in_progress', 'completed', 'cancelled']
        if new_status not in valid:
            return Response({'error': 'Invalid status'}, status=status.HTTP_400_BAD_REQUEST)

        booking.status = new_status
        if new_status == 'completed':
            booking.completed_at = timezone.now()
        booking.save()
        send_booking_notification.delay(booking.id, new_status)
        return Response(BookingSerializer(booking).data)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Dashboard stats for managers — scoped to their district"""
        if not self.check_role(request, ['manager']):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        district = request.user.district
        qs = Booking.objects.filter(farmer__district__iexact=district) if district else Booking.objects.all()
        op_qs = User.objects.filter(role='operator', district__iexact=district) if district else User.objects.filter(role='operator')
        farmer_qs = User.objects.filter(role='farmer', district__iexact=district) if district else User.objects.filter(role='farmer')
        dealer_qs = User.objects.filter(role='dealer', district__iexact=district) if district else User.objects.filter(role='dealer')
        return Response({
            'total_bookings': qs.count(),
            'in_progress': qs.filter(status='in_progress').count(),
            'completed': qs.filter(status='completed').count(),
            'total_revenue': float(qs.filter(status='completed').aggregate(s=models.Sum('amount'))['s'] or 0),
            'total_partners': op_qs.count(),
            'total_farmers': farmer_qs.count(),
            'total_dealers': dealer_qs.count(),
            'district': district,
        })


from django.db import models  # noqa: E402


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def rate_booking(request):
    """Rate a completed booking"""
    from .models import Rating
    booking_id = request.data.get('booking_id')
    rating_value = request.data.get('rating')
    review_text = request.data.get('review', '')

    booking = Booking.objects.filter(booking_id=booking_id, farmer=request.user, status='completed').first()
    if not booking:
        return Response({'error': 'Booking not found or not completed'}, status=status.HTTP_400_BAD_REQUEST)

    if hasattr(booking, 'rating'):
        return Response({'error': 'Already rated'}, status=status.HTTP_400_BAD_REQUEST)

    if not booking.operator:
        return Response({'error': 'No operator assigned'}, status=status.HTTP_400_BAD_REQUEST)

    Rating.objects.create(
        booking=booking,
        farmer=request.user,
        operator=booking.operator,
        rating=rating_value,
        review=review_text,
    )
    return Response({'status': 'ok', 'message': 'Rating submitted'})


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def service_pricing(request):
    """Get or update service pricing - admin/manager only for POST"""
    from .models import ServicePricing
    DEFAULT_PRICING = {
        'drone_spraying': 600, 'tractor_rental': 700, 'rotavator': 500,
        'harvester': 1000, 'seed_drill': 400, 'water_tanker': 800,
        'cultivator': 450, 'fertilizer_spraying': 550,
    }
    if request.method == 'GET':
        pricing = {}
        db_prices = {p.service: p.price_per_acre for p in ServicePricing.objects.all()}
        for svc, default in DEFAULT_PRICING.items():
            pricing[svc] = float(db_prices.get(svc, default))
        return Response(pricing)

    if request.user.role not in ('manager', 'admin'):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
    for svc, price in request.data.items():
        if svc in DEFAULT_PRICING:
            ServicePricing.objects.update_or_create(service=svc, defaults={'price_per_acre': price})
    return Response({'status': 'updated'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_user_role(request):
    """Update user role - admin/manager only"""
    if request.user.role not in ('manager', 'admin'):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
    user_id = request.data.get('user_id')
    new_role = request.data.get('role')
    valid_roles = ['farmer', 'operator', 'dealer', 'manager']
    if new_role not in valid_roles:
        return Response({'error': 'Invalid role'}, status=status.HTTP_400_BAD_REQUEST)
    user = User.objects.filter(id=user_id).first()
    if not user:
        return Response({'error': 'User not found'}, status=status.HTTP_404_NOT_FOUND)
    user.role = new_role
    user.save()
    return Response({'status': 'updated', 'user_id': user_id, 'role': new_role})


@api_view(['GET'])
@permission_classes([AllowAny])
def track_booking(request):
    """Public endpoint — look up booking by booking_id or farmer phone. No auth required."""
    booking_id = request.GET.get('booking_id', '').strip()
    phone = request.GET.get('phone', '').strip()

    if not booking_id and not phone:
        return Response({'error': 'Provide booking_id or phone'}, status=status.HTTP_400_BAD_REQUEST)

    if booking_id:
        qs = Booking.objects.filter(booking_id__iexact=booking_id)
    else:
        qs = Booking.objects.filter(farmer__phone=phone).order_by('-created_at')

    if not qs.exists():
        return Response({'error': 'No bookings found'}, status=status.HTTP_404_NOT_FOUND)

    def fmt(b):
        return {
            'booking_id': b.booking_id,
            'service': b.service.replace('_', ' ').title(),
            'crop': b.crop,
            'area_acres': str(b.area_acres),
            'scheduled_date': str(b.scheduled_date),
            'scheduled_time': b.scheduled_time,
            'location_address': b.location_address,
            'status': b.status,
            'amount': str(b.amount),
            'farmer_name': b.farmer.get_full_name() if b.farmer else '',
            'operator_name': b.operator.get_full_name() if b.operator else None,
            'operator_phone': b.operator.phone if b.operator else None,
            'created_at': b.created_at.strftime('%d %b %Y'),
        }

    if booking_id:
        return Response(fmt(qs.first()))
    return Response([fmt(b) for b in qs[:10]])


@api_view(['GET'])
@permission_classes([AllowAny])
def crops_list(request):
    """Return available crops from database"""
    from .models import Crop
    crops = list(Crop.objects.filter(is_active=True).values_list('name', flat=True))
    if not crops:
        crops = ['Paddy', 'Cotton', 'Maize', 'Sugarcane', 'Groundnut', 'Rice', 'Wheat', 'Soybean', 'Chilli', 'Turmeric']
    return Response({'crops': crops})


@api_view(['GET'])
@permission_classes([AllowAny])
def service_info(request):
    """Return service details and pricing"""
    service = request.GET.get('service', '')
    
    services_data = {
        'droneSpraying': {'description': 'Efficient aerial spraying using advanced drones', 'priceRange': '₹500 - ₹800 per acre', 'features': ['Covers up to 10 acres/hour', 'Uniform spray distribution', 'GPS-guided precision']},
        'tractorRental': {'description': 'Rent tractors for ploughing and transportation', 'priceRange': '₹500 - ₹800 per hour', 'features': ['Multiple HP options', 'Experienced operators', 'All attachments available']},
        'rotavator': {'description': 'Rotavator service for soil preparation', 'priceRange': '₹400 - ₹600 per acre', 'features': ['Deep soil mixing', 'Weed incorporation', 'Seedbed preparation']},
        'harvester': {'description': 'Combine harvester for efficient crop harvesting', 'priceRange': '₹800 - ₹1200 per acre', 'features': ['Multi-crop support', 'Minimal grain loss', 'Fast harvesting']},
        'seedDrill': {'description': 'Precision seed drilling for uniform sowing', 'priceRange': '₹300 - ₹500 per acre', 'features': ['Uniform seed placement', 'Adjustable row spacing', 'Depth control']},
        'waterTanker': {'description': 'Water tanker service for irrigation', 'priceRange': '₹500 - ₹1000 per trip', 'features': ['5000-10000 litre capacity', 'Quick delivery', 'Flexible scheduling']},
        'cultivator': {'description': 'Cultivator service for secondary tillage', 'priceRange': '₹350 - ₹550 per acre', 'features': ['Inter-row cultivation', 'Weed removal', 'Soil aeration']},
        'fertilizerSpraying': {'description': 'Professional fertilizer spraying service', 'priceRange': '₹400 - ₹700 per acre', 'features': ['Uniform application', 'Dosage control', 'Trained operators']},
    }
    
    data = services_data.get(service, {})
    return Response(data)



@api_view(['GET'])
@permission_classes([IsAuthenticated])
def check_operators(request):
    import math, re
    service = request.GET.get('service', '')
    district = request.GET.get('district', request.user.district or '')
    lat = request.GET.get('lat')
    lng = request.GET.get('lng')
    if not service:
        return Response({'error': 'service is required'}, status=400)
    # Handle both camelCase (droneSpraying) and snake_case (drone_spraying)
    if '_' in service:
        service_snake = service.lower()
    else:
        service_snake = re.sub(r'([A-Z])', r'_\1', service).lower().lstrip('_')
    operators = User.objects.filter(role='operator', is_active=True, is_on_duty=True)
    matching = [op for op in operators if service_snake in (op.services or [])]
    if district:
        district_match = [op for op in matching if op.district and op.district.lower() == district.lower()]
        if district_match:
            matching = district_match
    if lat and lng and matching:
        lat1, lng1 = float(lat), float(lng)
        def haversine(lat2, lon2):
            R = 6371
            dlat = math.radians(float(lat2) - lat1)
            dlon = math.radians(float(lon2) - lng1)
            a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(float(lat2))) * math.sin(dlon/2)**2
            return R * 2 * math.asin(math.sqrt(a))
        nearby = [op for op in matching if op.location_lat and op.location_lng and haversine(op.location_lat, op.location_lng) <= 30]
        if nearby:
            matching = nearby
    return Response({'available': len(matching) > 0, 'count': len(matching), 'service': service_snake, 'district': district})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def accept_booking(request):
    """Operator/lead partner accepts a pending booking"""
    import redis
    from django.conf import settings as s

    booking_id = request.data.get('booking_id')

    if request.user.role not in ('operator', 'dealer'):
        return Response({'error': 'Only operators or lead partners can accept bookings'}, status=status.HTTP_403_FORBIDDEN)

    booking = Booking.objects.filter(booking_id=booking_id, status='pending').first()
    if not booking:
        return Response({'error': 'Booking not available or already taken'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        r = redis.from_url(s.REDIS_URL)
        notified = r.get(f'booking:{booking_id}:notified')
        if notified:
            notified_ids = notified.decode().split(',')
            if str(request.user.id) not in notified_ids:
                return Response({'error': 'This booking was not offered to you'}, status=status.HTTP_403_FORBIDDEN)
        r.delete(f'booking:{booking_id}:notified')
    except Exception:
        pass

    booking.operator = request.user
    booking.status = 'confirmed'
    if booking.dealer:
        from .models import CommissionRule
        rate = CommissionRule.get_rate(booking.service, booking.farmer.district or '')
        booking.commission_amount = round(float(booking.amount) * rate / 100, 2)
    booking.save()

    from notifications.tasks import send_booking_notification
    send_booking_notification.delay(booking.id, 'operator_assigned')

    return Response({
        'status': 'accepted',
        'booking_id': booking.booking_id,
        'amount': booking.amount,
        'message': 'Booking accepted',
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_booking_price(request):
    """Admin/manager sets price on a booking — anytime or after receiving it"""
    if request.user.role not in ('manager', 'admin'):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

    booking_id = request.data.get('booking_id')
    price = request.data.get('price')

    if not price:
        return Response({'error': 'price is required'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        price = float(price)
        if price <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return Response({'error': 'price must be a positive number'}, status=status.HTTP_400_BAD_REQUEST)

    booking = Booking.objects.filter(booking_id=booking_id).first()
    if not booking:
        return Response({'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)

    booking.amount = price
    if booking.dealer:
        from .models import CommissionRule
        rate = CommissionRule.get_rate(booking.service, booking.farmer.district or '')
        booking.commission_amount = round(price * rate / 100, 2)
    booking.save()

    return Response({'status': 'updated', 'booking_id': booking_id, 'amount': price})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reject_booking(request):
    """Operator rejects/skips a booking"""
    booking_id = request.data.get('booking_id')
    return Response({'status': 'rejected', 'booking_id': booking_id})


@api_view(['GET', 'POST', 'DELETE'])
@permission_classes([IsAuthenticated])
def commission_rules(request):
    """Admin manages commission rules per service/district"""
    from .models import CommissionRule
    if request.user.role not in ('manager', 'admin'):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)

    if request.method == 'GET':
        rules = CommissionRule.objects.all()
        return Response([{
            'id': r.id,
            'service': r.service,
            'district': r.district,
            'commission_percent': float(r.commission_percent),
            'updated_at': r.updated_at.strftime('%d %b %Y'),
        } for r in rules])

    if request.method == 'POST':
        svc = request.data.get('service', '')
        district = request.data.get('district', '')
        percent = request.data.get('commission_percent')
        if percent is None:
            return Response({'error': 'commission_percent required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            percent = float(percent)
            if not (0 <= percent <= 100):
                raise ValueError
        except (ValueError, TypeError):
            return Response({'error': 'commission_percent must be 0-100'}, status=status.HTTP_400_BAD_REQUEST)
        rule, _ = CommissionRule.objects.update_or_create(
            service=svc, district=district,
            defaults={'commission_percent': percent}
        )
        return Response({'id': rule.id, 'service': rule.service, 'district': rule.district, 'commission_percent': float(rule.commission_percent)}, status=status.HTTP_201_CREATED)

    if request.method == 'DELETE':
        rule_id = request.data.get('id')
        CommissionRule.objects.filter(id=rule_id).delete()
        return Response({'status': 'deleted'})


    """Operator rejects/skips a booking"""
    booking_id = request.data.get('booking_id')
    # Just acknowledge - booking stays pending for others
    return Response({'status': 'rejected', 'booking_id': booking_id})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_operator_location(request):
    """Operator updates their live location"""
    lat = request.data.get('lat')
    lng = request.data.get('lng')
    if lat and lng:
        request.user.location_lat = lat
        request.user.location_lng = lng
        request.user.save()
    return Response({'status': 'ok'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dealer_stats(request):
    """Dealer dashboard stats"""
    from django.db.models import Sum, Count
    user = request.user
    bookings = Booking.objects.filter(dealer=user)
    total = bookings.count()
    completed = bookings.filter(status='completed').count()
    revenue = bookings.filter(status='completed').aggregate(s=Sum('amount'))['s'] or 0
    pending = bookings.filter(status__in=['pending', 'confirmed']).count()
    return Response({
        'total_bookings': total,
        'completed': completed,
        'pending': pending,
        'revenue': float(revenue),
    })
