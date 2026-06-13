"""
API Key Authentication Middleware
- Every request to /api/ must include X-API-Key header
- Protects backend from unauthorized access
- Works alongside JWT auth (API key = app-level, JWT = user-level)
"""

from django.conf import settings
from django.http import JsonResponse


class APIKeyMiddleware:
    """
    Middleware that requires a valid API key for all /api/ requests.
    The API key identifies the client app (mobile, admin web, etc).
    JWT token still required for user-specific endpoints.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only check /api/ routes (skip admin, static, etc)
        if request.path.startswith('/api/'):
            # Skip API key check for webhook (Razorpay calls this)
            if request.path == '/api/payments/webhook/':
                return self.get_response(request)

            api_key = request.headers.get('X-API-Key') or request.GET.get('api_key')

            if not api_key:
                return JsonResponse(
                    {'error': 'API key required. Include X-API-Key header.'},
                    status=401
                )

            valid_keys = getattr(settings, 'API_KEYS', [])
            if api_key not in valid_keys:
                return JsonResponse(
                    {'error': 'Invalid API key.'},
                    status=403
                )

        return self.get_response(request)
