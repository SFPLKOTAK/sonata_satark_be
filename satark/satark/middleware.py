import time
import jwt
from django.conf import settings
from authentication.user_tracking import record_api_log

class UserTrackingMiddleware:
    """
    Middleware that captures API requests, measure execution latency,
    extracts authenticated user details, and logs telemetry into user_api_logs table via raw SQL.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_time = time.time()
        response = self.get_response(request)
        duration_ms = int((time.time() - start_time) * 1000)

        # Ignore non-API / static / internal tracking & telemetry endpoints to avoid noise & recursion
        path = request.path
        if (path.startswith('/static/') or 
            path.startswith('/media/') or 
            path.startswith('/auth/session/') or 
            path.startswith('/auth/admin/analytics/')):
            return response

        session_id = request.headers.get('X-Session-ID', '')
        user_id = None
        usercode = 'ANONYMOUS'

        # Extract user identity from Authorization Bearer token if present
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
            try:
                payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
                user_id = payload.get('user_id')
                usercode = payload.get('usercode', 'ANONYMOUS')
            except Exception:
                pass

        # Extract client IP
        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        client_ip = x_forwarded.split(',')[0] if x_forwarded else request.META.get('REMOTE_ADDR', '')

        # Log asynchronously/safely without blocking response
        try:
            record_api_log(
                session_id=session_id,
                user_id=user_id,
                usercode=usercode,
                endpoint=path,
                method=request.method,
                status_code=response.status_code,
                response_time_ms=duration_ms,
                client_ip=client_ip
            )
        except Exception:
            pass

        return response
