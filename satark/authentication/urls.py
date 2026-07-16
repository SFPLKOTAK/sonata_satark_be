from django.urls import path
from .views import (
    login_view, refresh_view, menu_view,
    admin_menu_view, admin_save_menu_view,
    admin_user_list_view, admin_save_user_view, admin_geo_hierarchy_view,
    create_role_view, map_user_role_view, create_user_view,
)

urlpatterns = [
    path('login/', login_view, name='login'),
    path('refresh/', refresh_view, name='refresh'),
    path('menu/', menu_view, name='menu'),
    path('admin/menu/', admin_menu_view, name='admin_menu'),
    path('admin/menu/save/', admin_save_menu_view, name='admin_save_menu'),
    path('admin/users/', admin_user_list_view, name='admin_user_list'),
    path('admin/users/save/', admin_save_user_view, name='admin_save_user'),
    path('admin/users/geo/', admin_geo_hierarchy_view, name='admin_geo_hierarchy'),
    path('admin/roles/create/', create_role_view, name='create_role'),
    path('admin/users/map-role/', map_user_role_view, name='map_user_role'),
    path('admin/users/create/', create_user_view, name='create_user'),
]

