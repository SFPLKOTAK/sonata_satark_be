import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "satark.settings")

# Initialize Django ASGI application early to ensure the AppRegistry
# is fully populated before importing routing/models
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import Marklytix.routing

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AuthMiddlewareStack(
        URLRouter(
            Marklytix.routing.websocket_urlpatterns
        )
    ),
})
