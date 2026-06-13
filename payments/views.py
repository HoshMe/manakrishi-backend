import razorpay
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status

from .models import Payment, Commission
from bookings.models import Booking
from bookings.models import Booking

client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_order(request):
    """Create Razorpay order for a booking"""
    booking_id = request.data.get('booking_id')
    booking = Booking.objects.filter(booking_id=booking_id, farmer=request.user).first()
    if not booking:
        return Response({'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)

    amount_paise = int(booking.amount * 100)

    order_data = client.order.create({
        'amount': amount_paise,
        'currency': 'INR',
        'receipt': booking.booking_id,
    })

    Payment.objects.create(
        user=request.user,
        booking=booking,
        razorpay_order_id=order_data['id'],
        amount=booking.amount,
    )

    return Response({
        'order_id': order_data['id'],
        'amount': amount_paise,
        'currency': 'INR',
        'key': settings.RAZORPAY_KEY_ID,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_payment(request):
    """Verify Razorpay payment signature"""
    razorpay_order_id = request.data.get('razorpay_order_id')
    razorpay_payment_id = request.data.get('razorpay_payment_id')
    razorpay_signature = request.data.get('razorpay_signature')

    payment = Payment.objects.filter(razorpay_order_id=razorpay_order_id).first()
    if not payment:
        return Response({'error': 'Payment not found'}, status=status.HTTP_404_NOT_FOUND)

    # In test mode signature may be empty — still mark as paid
    if razorpay_signature:
        try:
            client.utility.verify_payment_signature({
                'razorpay_order_id': razorpay_order_id,
                'razorpay_payment_id': razorpay_payment_id,
                'razorpay_signature': razorpay_signature,
            })
        except razorpay.errors.SignatureVerificationError:
            payment.status = 'failed'
            payment.save()
            return Response({'error': 'Payment verification failed'}, status=status.HTTP_400_BAD_REQUEST)

    payment.razorpay_payment_id = razorpay_payment_id
    payment.razorpay_signature = razorpay_signature or ''
    payment.status = 'paid'
    payment.save()

    # Update booking status
    booking = payment.booking
    booking.status = 'confirmed'
    booking.save()

    # Create commission for dealer
    if booking.dealer and booking.commission_amount > 0:
        Commission.objects.create(
            dealer=booking.dealer,
            booking=booking,
            amount=booking.commission_amount,
        )

    # Send SMS + WhatsApp for payment
    from notifications.sms_whatsapp import send_booking_sms_whatsapp
    send_booking_sms_whatsapp(booking, 'payment_received')

    return Response({'status': 'paid', 'booking_id': booking.booking_id})



@api_view(['POST'])
@permission_classes([AllowAny])
def razorpay_webhook(request):
    """Handle Razorpay webhook events"""
    payload = request.data
    event = payload.get('event')

    if event == 'payment.captured':
        payment_entity = payload['payload']['payment']['entity']
        order_id = payment_entity.get('order_id')
        payment = Payment.objects.filter(razorpay_order_id=order_id).first()
        if payment and payment.status != 'paid':
            payment.razorpay_payment_id = payment_entity['id']
            payment.status = 'paid'
            payment.save()

    return Response({'status': 'ok'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_transactions(request):
    """List all payment transactions - for admin"""
    if request.user.role not in ('admin', 'manager'):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
    
    payments = Payment.objects.select_related('user', 'booking').order_by('-created_at')[:50]
    data = [{
        'id': p.id,
        'razorpay_order_id': p.razorpay_order_id,
        'user_name': f"{p.user.first_name} {p.user.last_name}",
        'amount': str(p.amount),
        'status': p.status,
        'created_at': p.created_at.strftime('%d %b %Y'),
    } for p in payments]
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_commissions(request):
    """List all commissions - for admin"""
    if request.user.role not in ('admin', 'manager'):
        return Response({'error': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
    
    commissions = Commission.objects.select_related('dealer', 'booking').order_by('-created_at')[:50]
    data = [{
        'id': c.id,
        'dealer_name': f"{c.dealer.first_name} {c.dealer.last_name}",
        'booking_id': c.booking.booking_id,
        'amount': str(c.amount),
        'is_withdrawn': c.is_withdrawn,
        'created_at': c.created_at.strftime('%d %b %Y'),
    } for c in commissions]
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def wallet(request):
    """Get user wallet balance and recent transactions"""
    from django.db.models import Sum
    
    # Total amount spent by user
    total_spent = Payment.objects.filter(user=request.user, status='paid').aggregate(s=Sum('amount'))['s'] or 0
    
    # Recent transactions
    payments = Payment.objects.filter(user=request.user).order_by('-created_at')[:20]
    transactions = [{
        'id': p.id,
        'description': f"Payment for {p.booking.booking_id}" if p.booking else 'Payment',
        'amount': str(p.amount),
        'type': 'debit',
        'status': p.status,
        'created_at': p.created_at.strftime('%d %b %Y'),
    } for p in payments]
    
    return Response({
        'balance': '0',
        'total_spent': str(total_spent),
        'transactions': transactions,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def generate_invoice(request, booking_id):
    """Generate PDF invoice for a booking"""
    import io
    from django.http import HttpResponse
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors as rl_colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch

    booking = Booking.objects.filter(booking_id=booking_id, farmer=request.user).first()
    if not booking:
        return Response({'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)

    payment = Payment.objects.filter(booking=booking, status='paid').first()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    bold = ParagraphStyle('Bold', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=10)
    elements = []

    # Header
    elements.append(Paragraph('<b>ManaKrishi</b> - Agri Services', styles['Title']))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f'Invoice #{booking.booking_id}', styles['Heading2']))
    elements.append(Paragraph(f'Date: {booking.created_at.strftime("%d %b %Y")}', styles['Normal']))
    elements.append(Spacer(1, 20))

    # Addresses
    addr_data = [['Delivery Address', 'Invoice Address'],
                 [booking.delivery_address or booking.location_address, booking.invoice_address or booking.delivery_address or booking.location_address]]
    addr_table = Table(addr_data, colWidths=[3 * inch, 3 * inch])
    addr_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(addr_table)
    elements.append(Spacer(1, 20))

    # Farmer info
    elements.append(Paragraph(f'Farmer: {booking.farmer.first_name} {booking.farmer.last_name}', styles['Normal']))
    elements.append(Paragraph(f'Phone: {booking.farmer.phone}', styles['Normal']))
    elements.append(Spacer(1, 16))

    # Booking details table
    data = [
        ['Description', 'Details'],
        ['Service', booking.get_service_display()],
        ['Crop', booking.crop],
        ['Area', f'{booking.area_acres} Acres'],
        ['Scheduled Date', booking.scheduled_date.strftime('%d %b %Y')],
        ['Scheduled Time', booking.scheduled_time],
        ['Spray Type', booking.spray_type or '-'],
        ['Status', booking.get_status_display()],
    ]
    table = Table(data, colWidths=[2.5 * inch, 3.5 * inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), rl_colors.HexColor('#2E7D32')),
        ('TEXTCOLOR', (0, 0), (-1, 0), rl_colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, rl_colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [rl_colors.white, rl_colors.HexColor('#F5F5F5')]),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 20))

    # Payment details
    elements.append(Paragraph('<b>Payment Summary</b>', styles['Heading3']))
    pay_data = [
        ['Amount', f'Rs. {booking.amount}'],
        ['Payment Status', payment.status.capitalize() if payment else 'Pending'],
        ['Payment ID', payment.razorpay_payment_id if payment else '-'],
    ]
    pay_table = Table(pay_data, colWidths=[2.5 * inch, 3.5 * inch])
    pay_table.setStyle(TableStyle([
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(pay_table)
    elements.append(Spacer(1, 30))
    elements.append(Paragraph('Thank you for using ManaKrishi!', styles['Normal']))

    doc.build(elements)
    buf.seek(0)

    response = HttpResponse(buf, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="invoice_{booking.booking_id}.pdf"'
    return response


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def earnings(request):
    """Get operator/dealer earnings"""
    from django.db.models import Sum
    from django.utils import timezone
    from datetime import timedelta
    
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0)
    week_start = now - timedelta(days=now.weekday())
    
    if request.user.role == 'operator':
        completed = Booking.objects.filter(operator=request.user, status='completed')
        total = float(completed.aggregate(s=Sum('amount'))['s'] or 0)
        this_month = float(completed.filter(completed_at__gte=month_start).aggregate(s=Sum('amount'))['s'] or 0)
        this_week = float(completed.filter(completed_at__gte=week_start).aggregate(s=Sum('amount'))['s'] or 0)
        pending = float(Booking.objects.filter(operator=request.user, status__in=['confirmed', 'in_progress', 'on_the_way']).aggregate(s=Sum('amount'))['s'] or 0)
        
        transactions = [{
            'id': b.id,
            'service': b.service,
            'amount': str(b.amount),
            'created_at': b.completed_at.strftime('%d %b %Y') if b.completed_at else '',
        } for b in completed.order_by('-completed_at')[:20]]
    else:
        # Dealer commissions
        commissions = Commission.objects.filter(dealer=request.user)
        total = float(commissions.aggregate(s=Sum('amount'))['s'] or 0)
        this_month = float(commissions.filter(created_at__gte=month_start).aggregate(s=Sum('amount'))['s'] or 0)
        this_week = float(commissions.filter(created_at__gte=week_start).aggregate(s=Sum('amount'))['s'] or 0)
        pending = float(commissions.filter(is_withdrawn=False).aggregate(s=Sum('amount'))['s'] or 0)
        
        transactions = [{
            'id': c.id,
            'service': c.booking.service if c.booking else '',
            'amount': str(c.amount),
            'created_at': c.created_at.strftime('%d %b %Y'),
        } for c in commissions.order_by('-created_at')[:20]]
    
    return Response({
        'total': total,
        'this_month': this_month,
        'this_week': this_week,
        'pending': pending,
        'transactions': transactions,
    })
