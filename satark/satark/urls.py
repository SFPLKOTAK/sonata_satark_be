#  no test
# ronaldo is the real bakri meeeeeeeeeeee.

from django.urls import path, include

urlpatterns = [
    path('marklytix/', include('Marklytix.urls')),
    path('auth/', include('authentication.urls')),
    path('planner/', include('planner.urls')),
    path('audit/', include('audit.urls')),
    path('loan-opportunity/', include('loan_opportunity.urls')),
]
