from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status

from .models import Notification, FAQ


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def list_notifications(request):
    notifications = Notification.objects.filter(user=request.user)[:50]
    data = [{
        'id': n.id,
        'type': n.type,
        'title': n.title,
        'body': n.body,
        'data': n.data,
        'is_read': n.is_read,
        'created_at': n.created_at.strftime('%d %b %Y, %I:%M %p'),
    } for n in notifications]
    return Response(data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_read(request):
    notif_id = request.data.get('id')
    if notif_id:
        Notification.objects.filter(id=notif_id, user=request.user).update(is_read=True)
    else:
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return Response({'status': 'ok'})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def unread_count(request):
    count = Notification.objects.filter(user=request.user, is_read=False).count()
    return Response({'unread_count': count})


@api_view(['GET'])
@permission_classes([AllowAny])
def help_faqs(request):
    faqs = FAQ.objects.filter(is_active=True)
    data = [{'id': f.id, 'question': f.question, 'answer': f.answer} for f in faqs]
    return Response({
        'faqs': data,
        'support': {
            'phone': '18001234567',
            'email': 'support@manakrishi.in',
            'whatsapp': '919876543210',
        }
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def test_push(request):
    """
    Test push notification endpoint.
    - If user has push_token: sends real FCM push
    - If not: simulates and returns what would be sent
    """
    user = request.user
    title = request.data.get('title', 'Test Notification')
    body = request.data.get('body', 'This is a test push from ManaKrishi backend')

    # Store in-app notification regardless
    Notification.objects.create(
        user=user,
        type='general',
        title=title,
        body=body,
        data={'type': 'test'},
    )

    if not user.push_token:
        return Response({
            'status': 'simulated',
            'message': 'No push_token on user. In-app notification created. To receive real push: login from the app on a physical device.',
            'would_send': {'title': title, 'body': body},
        })

    # Try sending real FCM push
    try:
        import firebase_admin
        from firebase_admin import messaging as fcm_messaging
        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        message = fcm_messaging.Message(
            notification=fcm_messaging.Notification(title=title, body=body),
            data={'type': 'test'},
            token=user.push_token,
        )
        response = fcm_messaging.send(message)
        return Response({
            'status': 'sent',
            'push_token': user.push_token,
            'title': title,
            'body': body,
            'fcm_response': str(response),
        })
    except Exception as e:
        return Response({
            'status': 'error',
            'error': str(e),
            'push_token': user.push_token,
        })
