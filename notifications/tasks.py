from celery import shared_task
from .sms_whatsapp import send_booking_sms_whatsapp


def _send_push(user, title, body, data=None):
    """Send push via Firebase Cloud Messaging"""
    if not user.push_token:
        return
    try:
        import firebase_admin
        from firebase_admin import messaging as fcm_messaging
        
        # Initialize Firebase if not already
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        
        message = fcm_messaging.Message(
            notification=fcm_messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
            token=user.push_token,
        )
        fcm_messaging.send(message)
    except Exception as e:
        print(f'FCM Push error: {e}')


def _create_notification(user, notif_type, title, body, data=None):
    """Store notification in DB"""
    from notifications.models import Notification
    Notification.objects.create(
        user=user,
        type=notif_type,
        title=title,
        body=body,
        data=data or {},
    )


@shared_task
def send_booking_notification(booking_id, event_type):
    """Send push + store in-app notification for booking events to ALL relevant users"""
    from bookings.models import Booking

    booking = Booking.objects.select_related('farmer', 'operator', 'dealer').get(id=booking_id)

    # Define who gets notified for each event
    # Each event can notify multiple users with different messages
    notifications = []

    if event_type == 'booking_confirmed':
        notifications.append((booking.farmer, 'Booking Confirmed!', f'Your {booking.get_service_display()} booking is confirmed for {booking.scheduled_date}.'))
        if booking.dealer:
            notifications.append((booking.dealer, 'New Booking Created', f'Booking {booking.booking_id} created for your farmer. Commission: ₹{booking.commission_amount}'))

    elif event_type == 'operator_assigned':
        notifications.append((booking.farmer, 'Operator Assigned', f'An operator has been assigned for your {booking.get_service_display()} service.'))
        if booking.operator:
            notifications.append((booking.operator, 'Job Assigned!', f'{booking.get_service_display()} - {booking.area_acres} acres at {booking.location_address}. Date: {booking.scheduled_date}'))
        if booking.dealer:
            notifications.append((booking.dealer, 'Operator Assigned', f'Operator assigned for booking {booking.booking_id}'))

    elif event_type == 'on_the_way':
        notifications.append((booking.farmer, 'Operator On The Way', 'Your operator is on the way to your field.'))

    elif event_type == 'in_progress':
        notifications.append((booking.farmer, 'Service Started', f'{booking.get_service_display()} service has started.'))
        if booking.operator:
            notifications.append((booking.operator, 'Service Started', f'You started {booking.get_service_display()} for booking {booking.booking_id}'))

    elif event_type == 'completed':
        notifications.append((booking.farmer, 'Service Completed ✓', f'{booking.get_service_display()} completed successfully! Amount: ₹{booking.amount}'))
        if booking.operator:
            notifications.append((booking.operator, 'Job Completed ✓', f'{booking.get_service_display()} completed. Earnings: ₹{booking.amount}'))
        if booking.dealer:
            notifications.append((booking.dealer, 'Booking Completed', f'Booking {booking.booking_id} completed. Commission: ₹{booking.commission_amount}'))

    elif event_type == 'new_order' and booking.operator:
        notifications.append((booking.operator, 'New Order!', f'New {booking.get_service_display()} order - {booking.area_acres} acres.'))

    # Send to all recipients
    data = {'type': event_type, 'booking_id': booking.booking_id}
    for user, title, body in notifications:
        if not user:
            continue
        _create_notification(user, event_type, title, body, data)
        _send_push(user, title, body, data)

    # Send SMS + WhatsApp
    event_map = {
        'booking_confirmed': 'booking_created',
        'operator_assigned': 'operator_found',
        'on_the_way': 'operator_on_way',
        'in_progress': 'service_started',
        'completed': 'service_completed',
    }
    sms_event = event_map.get(event_type)
    if sms_event:
        send_booking_sms_whatsapp(booking, sms_event)


@shared_task
def send_push_to_user(user_id, title, body, notif_type='general', data=None):
    """Send push + store notification for a specific user"""
    from accounts.models import User

    user = User.objects.get(id=user_id)
    _create_notification(user, notif_type, title, body, data)
    _send_push(user, title, body, data)


@shared_task
def send_push_to_role(role, title, body, notif_type='general', data=None):
    """Send push + store notification for all users of a role"""
    from accounts.models import User

    users = User.objects.filter(role=role)

    for user in users:
        _create_notification(user, notif_type, title, body, data)
        _send_push(user, title, body, data)


@shared_task
def assign_booking_to_nearby_operators(booking_id):
    """
    Find nearby operators and notify them about the new booking.
    Works like taxi dispatch - sends to closest operators first.
    """
    from bookings.models import Booking
    from accounts.models import User
    from math import radians, cos, sin, asin, sqrt

    booking = Booking.objects.get(id=booking_id)
    
    if not booking.location_lat or not booking.location_lng:
        return {'status': 'no_location'}

    # Find all active operators with location
    operators = User.objects.filter(
        role='operator',
        is_active=True,
    ).exclude(location_lat=None).exclude(location_lng=None)

    # Calculate distance and sort by nearest
    def haversine(lat1, lon1, lat2, lon2):
        lat1, lon1, lat2, lon2 = map(radians, [float(lat1), float(lon1), float(lat2), float(lon2)])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        return 6371 * 2 * asin(sqrt(a))  # km

    nearby = []
    for op in operators:
        dist = haversine(booking.location_lat, booking.location_lng, op.location_lat, op.location_lng)
        if dist <= 50:  # Within 50km radius
            nearby.append((op, dist))

    # Sort by distance
    nearby.sort(key=lambda x: x[1])

    # Notify top 5 nearest operators
    notified = []
    for op, dist in nearby[:5]:
        _create_notification(
            op, 'new_order',
            'New Order Nearby!',
            f'{booking.get_service_display()} - {booking.area_acres} acres, {dist:.1f}km away',
            {'type': 'new_order', 'booking_id': booking.booking_id, 'distance_km': round(dist, 1)}
        )
        _send_push(
            op,
            'New Order Nearby!',
            f'{booking.get_service_display()} - {booking.area_acres} acres, {dist:.1f}km away',
            {'type': 'new_order', 'booking_id': booking.booking_id}
        )
        notified.append(op.id)

    # Store notified operators on booking for tracking
    booking.status = 'pending'
    booking.save()

    # Store in Redis which operators were notified (expires in 10 min)
    import redis
    from django.conf import settings
    r = redis.from_url(settings.REDIS_URL)
    r.setex(f'booking:{booking.booking_id}:notified', 600, ','.join(map(str, notified)))

    return {'notified': len(notified), 'operators': notified}
