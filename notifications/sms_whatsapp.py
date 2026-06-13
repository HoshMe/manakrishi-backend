"""
SMS & WhatsApp Notification Service
- SMS: AWS End User Messaging (Pinpoint SMS Voice V2)
- WhatsApp: WhatsApp Business API via Meta Cloud API

Every booking action triggers both SMS and WhatsApp to the relevant user.
"""

import boto3
import requests
from django.conf import settings


# ─── SMS via AWS ──────────────────────────────────────────────────────────────

def send_sms(phone, message):
    """Send SMS via AWS End User Messaging"""
    if not phone:
        return False
    try:
        client = boto3.client(
            'pinpoint-sms-voice-v2',
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_SMS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SMS_SECRET_ACCESS_KEY,
        )
        client.send_text_message(
            DestinationPhoneNumber=phone,
            OriginationIdentity=settings.AWS_SMS_ORIGINATION_ID,
            MessageBody=message,
            MessageType='TRANSACTIONAL',
        )
        return True
    except Exception as e:
        print(f'SMS Error: {e}')
        return False


# ─── WhatsApp via Meta Cloud API ─────────────────────────────────────────────

WHATSAPP_API_URL = f"https://graph.facebook.com/v18.0/{getattr(settings, 'WHATSAPP_PHONE_NUMBER_ID', '')}/messages"
WHATSAPP_TOKEN = getattr(settings, 'WHATSAPP_ACCESS_TOKEN', '')


def send_whatsapp(phone, message):
    """Send WhatsApp message via Meta Cloud API"""
    if not phone or not WHATSAPP_TOKEN:
        return False

    # Format phone: remove + prefix for WhatsApp API
    wa_phone = phone.lstrip('+')

    try:
        headers = {
            'Authorization': f'Bearer {WHATSAPP_TOKEN}',
            'Content-Type': 'application/json',
        }
        payload = {
            'messaging_product': 'whatsapp',
            'to': wa_phone,
            'type': 'text',
            'text': {'body': message},
        }
        resp = requests.post(WHATSAPP_API_URL, json=payload, headers=headers)
        return resp.status_code == 200
    except Exception as e:
        print(f'WhatsApp Error: {e}')
        return False


# ─── Unified Notification Sender ─────────────────────────────────────────────

def notify_user(user, message):
    """Send both SMS and WhatsApp to a user"""
    if not user or not user.phone:
        return
    send_sms(user.phone, message)
    send_whatsapp(user.phone, message)


# ─── Booking Event Messages ──────────────────────────────────────────────────

MESSAGES = {
    'booking_created': {
        'farmer': 'ManaKrishi: Your {service} booking ({booking_id}) has been placed. We are finding an operator near you.',
        'operator': None,
    },
    'operator_found': {
        'farmer': 'ManaKrishi: Good news! An operator has been found for your {service} booking ({booking_id}). They will arrive on {date}.',
        'operator': 'ManaKrishi: New job assigned! {service} - {area} acres at {location}. Booking ID: {booking_id}. Date: {date}.',
    },
    'operator_on_way': {
        'farmer': 'ManaKrishi: Your operator is on the way to your field for {service} ({booking_id}).',
        'operator': None,
    },
    'service_started': {
        'farmer': 'ManaKrishi: {service} has started on your field ({booking_id}). You will be notified on completion.',
        'operator': None,
    },
    'service_completed': {
        'farmer': 'ManaKrishi: {service} completed successfully! ({booking_id}). Amount: ₹{amount}. Thank you for using ManaKrishi!',
        'operator': 'ManaKrishi: Job completed! {service} ({booking_id}). Earnings: ₹{amount} credited.',
    },
    'payment_received': {
        'farmer': 'ManaKrishi: Payment of ₹{amount} received for booking {booking_id}. Thank you!',
        'operator': 'ManaKrishi: Payment of ₹{amount} for booking {booking_id} has been processed.',
    },
    'booking_cancelled': {
        'farmer': 'ManaKrishi: Your booking {booking_id} has been cancelled.',
        'operator': 'ManaKrishi: Booking {booking_id} has been cancelled by the farmer.',
    },
}


def send_booking_sms_whatsapp(booking, event):
    """Send SMS + WhatsApp for a booking event to relevant users"""
    templates = MESSAGES.get(event, {})

    context = {
        'service': booking.get_service_display(),
        'booking_id': booking.booking_id,
        'area': str(booking.area_acres),
        'location': booking.location_address,
        'date': str(booking.scheduled_date),
        'amount': str(booking.amount),
    }

    # Notify farmer
    farmer_msg = templates.get('farmer')
    if farmer_msg and booking.farmer:
        notify_user(booking.farmer, farmer_msg.format(**context))

    # Notify operator
    operator_msg = templates.get('operator')
    if operator_msg and booking.operator:
        notify_user(booking.operator, operator_msg.format(**context))
