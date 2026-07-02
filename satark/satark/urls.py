from django.urls import path, include

urlpatterns = [
    path('auth/', include('authentication.urls')),
    path('planner/', include('planner.urls')),
    path('audit/', include('audit.urls')),
]
