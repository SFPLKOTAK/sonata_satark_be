from django.urls import re_path
from .consumers import HierarchicalSearchConsumer, ChatHistoryConsumer

websocket_urlpatterns = [
    re_path(r"ws/history/$", ChatHistoryConsumer.as_asgi()),
    re_path(r"ws/marklytix-chat/(?P<prompt_name>[^/]+)/$", HierarchicalSearchConsumer.as_asgi()),
    re_path(r"ws/hierarchical-search/(?P<prompt_name>[^/]+)/$", HierarchicalSearchConsumer.as_asgi()),
    re_path(r"ws/spl_dwsf_combined/(?P<prompt_name>[^/]+)/$", HierarchicalSearchConsumer.as_asgi()),
    re_path(r"ws/spl_dwsf_combined/$", HierarchicalSearchConsumer.as_asgi()),
]
