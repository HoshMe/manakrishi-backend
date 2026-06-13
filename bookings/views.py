from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny

from .models import Booking
from .serializers import BookingSerializer, CreateBookingSerializer
from notifications.tasks import send_booking_notification


class IsRole:
    """Mixin to check user role"""
    def check_role(self, request, allowed_roles):
        return request.user.role in allowed_roles


class BookingViewSet(viewsets.ModelViewSet, IsRole):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'booking_id'

    def get_queryset(self):
        user = self.request.user
        if user.role == 'farmer':
            return Booking.objects.filter(farmer=user)
        elif user.role == 'operator':
            return Booking.objects.filter(operator=user)
        elif user.role == 'dealer':
            return Booking.objects.filter(dealer=user)
        elif user.role in ('manager', 'admin'):
            return Booking.objects.all()
        return Booking.objects.none()

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
        # Calculate amount based on service and area
        data = serializer.validated_data
        service = data.get('service', '')
        area = float(data.get('area_acres', 0))

        # Pricing per acre/unit
        pricing = {
            'drone_spraying': 600,
            'tractor_rental': 700,
            'rotavator': 500,
            'harvester': 1000,
            'seed_drill': 400,
            'water_tanker': 800,
            'cultivator': 450,
            'fertilizer_spraying': 550,
        }
        rate = pricing.get(service, 500)
        amount = rate * area

        # Create booking in 'pending' status - waiting for operator to accept
        # If dealer is creating on behalf of a farmer, set dealer field
        if self.request.user.role == 'dealer':
            farmer_id = self.request.data.get('farmer_id')
            if farmer_id:
                from accounts.models import User
                farmer = User.objects.filter(id=farmer_id, role='farmer').first()
                booking = serializer.save(farmer=farmer or self.request.user, dealer=self.request.user, status='pending', amount=amount)
            else:
                booking = serializer.save(farmer=self.request.user, dealer=self.request.user, status='pending', amount=amount)
        else:
            booking = serializer.save(farmer=self.request.user, status='pending', amount=amount)
        # Calculate commission (10% for dealer)
        if booking.dealer:
            booking.commission_amount = booking.amount * 0.10
            booking.save()

        # Dispatch to nearby operators (like taxi booking)
        from notifications.tasks import assign_booking_to_nearby_operators
        assign_booking_to_nearby_operators.delay(booking.id)

        send_booking_notification.delay(booking.id, 'booking_confirmed')

    @action(detail=True, methods=['post'])
    def assign_operator(self, request, pk=None):
        if not self.check_role(request, ['manager', 'admin']):
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
        """Dashboard stats for managers/admin"""
        if not self.check_role(request, ['manager', 'admin']):
            return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
        from accounts.models import User
        qs = Booking.objects.all()
        return Response({
            'total_bookings': qs.count(),
            'in_progress': qs.filter(status='in_progress').count(),
            'completed': qs.filter(status='completed').count(),
            'total_revenue': float(qs.filter(status='completed').aggregate(s=models.Sum('amount'))['s'] or 0),
            'total_partners': User.objects.filter(role='operator').count(),
            'total_farmers': User.objects.filter(role='farmer').count(),
            'total_dealers': User.objects.filter(role='dealer').count(),
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


@api_view(['GET'])
@permission_classes([AllowAny])
def crops_list(request):
    """Return available crops from database"""
    from .models import Crop
    crops = list(Crop.objects.filter(is_active=True).values_list('name', flat=True))
    if not crops:
        # Fallback if no crops added yet
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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def accept_booking(request):
    """Operator accepts a pending booking - first come first served"""
    import redis
    from django.conf import settings as s

    booking_id = request.data.get('booking_id')
    if request.user.role != 'operator':
        return Response({'error': 'Only operators can accept bookings'}, status=status.HTTP_403_FORBIDDEN)

    booking = Booking.objects.filter(booking_id=booking_id, status='pending').first()
    if not booking:
        return Response({'error': 'Booking not available or already taken'}, status=status.HTTP_400_BAD_REQUEST)

    # Check if this operator was notified (optional - can remove for open dispatch)
    r = redis.from_url(s.REDIS_URL)
    notified = r.get(f'booking:{booking_id}:notified')
    if notified:
        notified_ids = notified.decode().split(',')
        if str(request.user.id) not in notified_ids:
            return Response({'error': 'This booking was not offered to you'}, status=status.HTTP_403_FORBIDDEN)

    # Assign to this operator (first come first served)
    booking.operator = request.user
    booking.status = 'confirmed'
    booking.save()

    # Clear Redis key so others can't accept
    r.delete(f'booking:{booking_id}:notified')

    # Notify farmer that operator accepted
    from notifications.tasks import send_booking_notification
    send_booking_notification.delay(booking.id, 'operator_assigned')

    return Response({
        'status': 'accepted',
        'booking_id': booking.booking_id,
        'message': 'Booking assigned to you',
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reject_booking(request):
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
