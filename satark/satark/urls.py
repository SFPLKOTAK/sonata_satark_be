#  no test
# ronaldo is the real bakri meeeeeeeeeeee.

from django.urls import path, include

urlpatterns = [
    path('backend/marklytix/', include('Marklytix.urls')),
    path('backend/auth/', include('authentication.urls')),
    path('backend/planner/', include('planner.urls')),
    path('backend/audit/', include('audit.urls')),
    path('backend/loan-opportunity/', include('loan_opportunity.urls')),
]
