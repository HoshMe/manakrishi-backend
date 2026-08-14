"""
E2E test: Complete booking workflow — farmer creates booking → operator assignment → acceptance
Covers the full flow from API to DB to verify why orders are not assigning to operators.
"""
from unittest.mock import patch, MagicMock
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from accounts.models import User
from bookings.models import Booking


def get_token(user):
    return str(RefreshToken.for_user(user).access_token)


class BookingWorkflowE2ETest(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.client.credentials(HTTP_X_API_KEY='mk-dev-key-2024')

        # Farmer in Hyderabad
        self.farmer = User.objects.create_user(
            username='+919999999999', phone='+919999999999',
            first_name='Test', last_name='Farmer',
            role='farmer', district='Hyderabad', state='Telangana',
        )

        # Operator in Hyderabad — on duty, with location and services
        self.operator = User.objects.create_user(
            username='+919000000002', phone='+919000000002',
            first_name='Test', last_name='Operator',
            role='operator', district='Hyderabad', state='Telangana',
            is_on_duty=True,
            location_lat=17.3850, location_lng=78.4867,
            services=['drone_spraying'],
        )

        # Operator NOT on duty — should NOT receive booking
        self.operator_off_duty = User.objects.create_user(
            username='+919000000099', phone='+919000000099',
            first_name='Off', last_name='Duty',
            role='operator', district='Hyderabad',
            is_on_duty=False,
            location_lat=17.3850, location_lng=78.4867,
            services=['drone_spraying'],
        )

        # Operator with no location — should NOT receive booking
        self.operator_no_location = User.objects.create_user(
            username='+919000000098', phone='+919000000098',
            first_name='No', last_name='Location',
            role='operator', district='Hyderabad',
            is_on_duty=True,
            location_lat=None, location_lng=None,
            services=['drone_spraying'],
        )

        self.booking_payload = {
            'service': 'drone_spraying',
            'crop': 'Paddy',
            'area_acres': '2.5',
            'scheduled_date': '2026-09-01',
            'scheduled_time': '09:00 AM',
            'location_address': 'Test Farm, Hyderabad',
            'location_lat': '17.3850',
            'location_lng': '78.4867',
        }

    # ── Step 1: Farmer login ──────────────────────────────────────────────────

    def test_01_farmer_can_login(self):
        token = get_token(self.farmer)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}', HTTP_X_API_KEY='mk-dev-key-2024')
        res = self.client.get('/api/auth/profile/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['role'], 'farmer')

    # ── Step 2: Farmer creates booking ───────────────────────────────────────

    @patch('notifications.tasks.assign_booking_to_nearby_operators.delay')
    @patch('notifications.tasks.send_booking_notification.delay')
    def test_02_farmer_creates_booking(self, mock_notif, mock_assign):
        token = get_token(self.farmer)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}', HTTP_X_API_KEY='mk-dev-key-2024')

        res = self.client.post('/api/bookings/', self.booking_payload, format='json')

        self.assertEqual(res.status_code, 201, f"Booking creation failed: {res.data}")
        self.assertIn('booking_id', res.data)
        self.assertEqual(res.data['status'], 'pending')
        self.assertEqual(res.data['operator'], None)  # No operator yet

        # Celery tasks must be dispatched
        mock_assign.assert_called_once()
        mock_notif.assert_called_once()

        self.booking_id = res.data['booking_id']

    # ── Step 3: assign_booking_to_nearby_operators task logic ────────────────

    @patch('notifications.tasks._send_push')
    @patch('notifications.tasks._create_notification')
    @patch('redis.from_url')
    def test_03_assign_task_notifies_nearby_operator(self, mock_redis, mock_notif, mock_push):
        mock_r = MagicMock()
        mock_redis.return_value = mock_r

        # Create booking directly (bypass Celery)
        booking = Booking.objects.create(
            farmer=self.farmer,
            service='drone_spraying', crop='Paddy', area_acres=2.5,
            scheduled_date='2026-09-01', scheduled_time='09:00 AM',
            location_address='Test Farm, Hyderabad',
            location_lat=17.3850, location_lng=78.4867,
            status='pending', amount=0,
        )

        from notifications.tasks import assign_booking_to_nearby_operators
        result = assign_booking_to_nearby_operators(booking.id)

        # Should notify at least 1 operator
        self.assertGreater(result['notified'], 0, "No operators were notified — this is the assignment bug")
        self.assertIn(self.operator.id, result['operators'])

        # Off-duty operator must NOT be notified
        self.assertNotIn(self.operator_off_duty.id, result['operators'],
                         "Off-duty operator should not receive booking")

        # No-location operator must NOT be notified
        self.assertNotIn(self.operator_no_location.id, result['operators'],
                         "Operator without location should not receive booking")

        # Redis key must be set for accept_booking to validate
        mock_r.setex.assert_called_once()
        redis_key = mock_r.setex.call_args[0][0]
        self.assertEqual(redis_key, f'booking:{booking.booking_id}:notified')

        # Push notification must be sent to operator
        push_recipients = [call[0][0] for call in mock_push.call_args_list]
        self.assertIn(self.operator, push_recipients,
                      "Operator did not receive push notification")

    # ── Step 4: Operator sees the booking in their orders list ───────────────

    @patch('notifications.tasks.assign_booking_to_nearby_operators.delay')
    @patch('notifications.tasks.send_booking_notification.delay')
    def test_04_operator_sees_pending_booking(self, mock_notif, mock_assign):
        # Create booking as farmer
        token = get_token(self.farmer)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}', HTTP_X_API_KEY='mk-dev-key-2024')
        self.client.post('/api/bookings/', self.booking_payload, format='json')

        # Operator fetches pending orders
        token = get_token(self.operator)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}', HTTP_X_API_KEY='mk-dev-key-2024')
        res = self.client.get('/api/bookings/?status=pending')

        self.assertEqual(res.status_code, 200)
        bookings = res.data if isinstance(res.data, list) else res.data.get('results', res.data)
        self.assertGreater(len(bookings), 0,
                           "Operator cannot see pending bookings — district filter may be broken")

    # ── Step 5: Operator accepts the booking ─────────────────────────────────

    @patch('notifications.tasks.send_booking_notification.delay')
    @patch('redis.from_url')
    def test_05_operator_accepts_booking(self, mock_redis, mock_notif):
        # Pre-set Redis to simulate operator was notified
        booking = Booking.objects.create(
            farmer=self.farmer,
            service='drone_spraying', crop='Paddy', area_acres=2.5,
            scheduled_date='2026-09-01', scheduled_time='09:00 AM',
            location_address='Test Farm, Hyderabad',
            location_lat=17.3850, location_lng=78.4867,
            status='pending', amount=0,
        )

        mock_r = MagicMock()
        mock_r.get.return_value = str(self.operator.id).encode()
        mock_redis.return_value = mock_r

        token = get_token(self.operator)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}', HTTP_X_API_KEY='mk-dev-key-2024')

        res = self.client.post('/api/bookings/accept/', {'booking_id': booking.booking_id}, format='json')

        self.assertEqual(res.status_code, 200, f"Accept failed: {res.data}")
        self.assertEqual(res.data['status'], 'accepted')

        booking.refresh_from_db()
        self.assertEqual(booking.operator, self.operator, "Operator not assigned to booking after accept")
        self.assertEqual(booking.status, 'confirmed', "Booking status not updated to confirmed")

    # ── Step 6: Operator cannot accept a booking they were NOT notified for ──

    @patch('redis.from_url')
    def test_06_operator_cannot_accept_unnotified_booking(self, mock_redis):
        booking = Booking.objects.create(
            farmer=self.farmer,
            service='drone_spraying', crop='Paddy', area_acres=2.5,
            scheduled_date='2026-09-01', scheduled_time='09:00 AM',
            location_address='Test Farm, Hyderabad',
            location_lat=17.3850, location_lng=78.4867,
            status='pending', amount=0,
        )

        # Redis returns a DIFFERENT operator's id
        mock_r = MagicMock()
        mock_r.get.return_value = b'9999'  # not self.operator.id
        mock_redis.return_value = mock_r

        token = get_token(self.operator)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}', HTTP_X_API_KEY='mk-dev-key-2024')

        res = self.client.post('/api/bookings/accept/', {'booking_id': booking.booking_id}, format='json')
        self.assertEqual(res.status_code, 403)

    # ── Step 7: Full status progression ──────────────────────────────────────

    @patch('notifications.tasks.send_booking_notification.delay')
    def test_07_full_status_progression(self, mock_notif):
        booking = Booking.objects.create(
            farmer=self.farmer, operator=self.operator,
            service='drone_spraying', crop='Paddy', area_acres=2.5,
            scheduled_date='2026-09-01', scheduled_time='09:00 AM',
            location_address='Test Farm, Hyderabad',
            location_lat=17.3850, location_lng=78.4867,
            status='confirmed', amount=1500,
        )

        token = get_token(self.operator)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}', HTTP_X_API_KEY='mk-dev-key-2024')

        for next_status in ['on_the_way', 'in_progress', 'completed']:
            res = self.client.post(
                f'/api/bookings/{booking.booking_id}/update_status/',
                {'status': next_status}, format='json'
            )
            self.assertEqual(res.status_code, 200, f"Status update to '{next_status}' failed: {res.data}")
            booking.refresh_from_db()
            self.assertEqual(booking.status, next_status)

        self.assertIsNotNone(booking.completed_at)

    # ── Step 8: Farmer sees booking with operator details ────────────────────

    @patch('notifications.tasks.send_booking_notification.delay')
    def test_08_farmer_sees_assigned_operator(self, mock_notif):
        booking = Booking.objects.create(
            farmer=self.farmer, operator=self.operator,
            service='drone_spraying', crop='Paddy', area_acres=2.5,
            scheduled_date='2026-09-01', scheduled_time='09:00 AM',
            location_address='Test Farm, Hyderabad',
            location_lat=17.3850, location_lng=78.4867,
            status='confirmed', amount=1500,
        )

        token = get_token(self.farmer)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}', HTTP_X_API_KEY='mk-dev-key-2024')

        res = self.client.get(f'/api/bookings/{booking.booking_id}/')
        self.assertEqual(res.status_code, 200)
        self.assertIsNotNone(res.data.get('operator'), "Farmer cannot see assigned operator")


class OperatorAssignmentBugTest(TestCase):
    """
    Targeted tests to isolate exactly why operators are not being assigned.
    """

    def setUp(self):
        self.client = APIClient()
        self.client.credentials(HTTP_X_API_KEY='mk-dev-key-2024')

        self.farmer = User.objects.create_user(
            username='+910000000001', phone='+910000000001',
            role='farmer', district='Hyderabad',
            first_name='Bug', last_name='Farmer',
        )

    def _make_operator(self, **kwargs):
        defaults = dict(
            role='operator', district='Hyderabad',
            is_on_duty=True, is_active=True,
            location_lat=17.3850, location_lng=78.4867,
            services=['drone_spraying'],
        )
        defaults.update(kwargs)
        i = User.objects.filter(role='operator').count()
        return User.objects.create_user(
            username=f'+91800000{i:04d}', phone=f'+91800000{i:04d}',
            first_name='Op', last_name=str(i), **defaults
        )

    def _make_booking(self, **kwargs):
        defaults = dict(
            farmer=self.farmer, service='drone_spraying', crop='Paddy',
            area_acres=2.5, scheduled_date='2026-09-01', scheduled_time='09:00 AM',
            location_address='Hyderabad', location_lat=17.3850, location_lng=78.4867,
            status='pending', amount=0,
        )
        defaults.update(kwargs)
        return Booking.objects.create(**defaults)

    @patch('notifications.tasks._send_push')
    @patch('notifications.tasks._create_notification')
    @patch('redis.from_url')
    def test_bug_no_location_on_booking(self, mock_redis, mock_notif, mock_push):
        """BUG CHECK: booking has no lat/lng → task returns early → no operator notified"""
        mock_redis.return_value = MagicMock()
        self._make_operator()
        booking = self._make_booking(location_lat=None, location_lng=None)

        from notifications.tasks import assign_booking_to_nearby_operators
        result = assign_booking_to_nearby_operators(booking.id)

        self.assertEqual(result['status'], 'no_location',
                         "Task should return no_location when booking has no coordinates")
        self.assertEqual(mock_push.call_count, 0,
                         "BUG CONFIRMED: No operators notified because booking has no location")

    @patch('notifications.tasks._send_push')
    @patch('notifications.tasks._create_notification')
    @patch('redis.from_url')
    def test_bug_operator_not_on_duty(self, mock_redis, mock_notif, mock_push):
        """BUG CHECK: all operators are off duty → no one gets notified"""
        mock_redis.return_value = MagicMock()
        self._make_operator(is_on_duty=False)
        booking = self._make_booking()

        from notifications.tasks import assign_booking_to_nearby_operators
        result = assign_booking_to_nearby_operators(booking.id)

        self.assertEqual(result['notified'], 0,
                         "BUG CONFIRMED: No operators notified because all are off duty")

    @patch('notifications.tasks._send_push')
    @patch('notifications.tasks._create_notification')
    @patch('redis.from_url')
    def test_bug_operator_too_far(self, mock_redis, mock_notif, mock_push):
        """BUG CHECK: operator is >50km away → not notified"""
        mock_redis.return_value = MagicMock()
        # Mumbai coordinates — far from Hyderabad booking
        self._make_operator(location_lat=19.0760, location_lng=72.8777, district='Mumbai')
        booking = self._make_booking()

        from notifications.tasks import assign_booking_to_nearby_operators
        result = assign_booking_to_nearby_operators(booking.id)

        self.assertEqual(result['notified'], 0,
                         "BUG CONFIRMED: No operators notified because all are >50km away")

    @patch('notifications.tasks._send_push')
    @patch('notifications.tasks._create_notification')
    @patch('redis.from_url')
    def test_bug_operator_no_push_token(self, mock_redis, mock_notif, mock_push):
        """BUG CHECK: operator has no push token → notification stored but push silently skipped"""
        mock_redis.return_value = MagicMock()
        self._make_operator(push_token='')  # empty string = no token registered
        booking = self._make_booking()

        from notifications.tasks import assign_booking_to_nearby_operators
        result = assign_booking_to_nearby_operators(booking.id)

        # Operator IS notified (in-app), but push is skipped
        self.assertGreater(result['notified'], 0, "Operator should still be notified in-app")
        # _send_push is called but internally skips due to no push_token
        mock_notif.assert_called()  # in-app notification created
