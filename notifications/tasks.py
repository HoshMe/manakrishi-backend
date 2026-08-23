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
    Assign booking to operators based on district + service type.
    No GPS required. Falls back: same district → any active operator.
    """
    from bookings.models import Booking
    from accounts.models import User

    booking = Booking.objects.select_related('farmer').get(id=booking_id)
    service = booking.service
    farmer_district = (booking.farmer.district or '').strip().lower() if booking.farmer else ''

    # All active on-duty operators
    base_qs = User.objects.filter(role='operator', is_active=True, is_on_duty=True)

    # Step 1: same district + matching service
    if farmer_district:
        candidates = [op for op in base_qs.filter(district__iexact=farmer_district)
                      if service in (op.services or []) or not op.services]
    else:
        candidates = []

    # Step 2: same district, any service
    if not candidates and farmer_district:
        candidates = list(base_qs.filter(district__iexact=farmer_district))

    # Step 3: matching service, any district
    if not candidates:
        candidates = [op for op in base_qs if service in (op.services or []) or not op.services]

    # Step 4: any active on-duty operator
    if not candidates:
        candidates = list(base_qs)

    notified = []
    for op in candidates[:5]:
        area_label = booking.farmer.district or 'your area' if booking.farmer else 'your area'
        _create_notification(
            op, 'new_order',
            'New Order Available!',
            f'{booking.get_service_display()} — {booking.area_acres} acres in {area_label}',
            {'type': 'new_order', 'booking_id': booking.booking_id}
        )
        _send_push(
            op,
            'New Order Available!',
            f'{booking.get_service_display()} — {booking.area_acres} acres in {area_label}',
            {'type': 'new_order', 'booking_id': booking.booking_id}
        )
        notified.append(op.id)

    try:
        import redis
        from django.conf import settings
        r = redis.from_url(settings.REDIS_URL)
        r.setex(f'booking:{booking.booking_id}:notified', 600, ','.join(map(str, notified)))
    except Exception:
        pass

    return {'notified': len(notified), 'operators': notified}
