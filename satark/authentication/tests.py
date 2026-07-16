import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'satark.settings')
django.setup()

from unittest import TestCase
from satark.cqrs import dispatcher
from . import views
from .queries import GetMenuQuery, GetMenuQueryHandler
from .commands import LoginCommand, LoginCommandHandler

class AuthCQRSTests(TestCase):
    def test_get_menu_query_registered(self):
        query = GetMenuQuery(user_db_id=1)
        handler = dispatcher._query_handlers.get(query.__class__)
        self.assertIsNotNone(handler)
        self.assertIsInstance(handler, GetMenuQueryHandler)

    def test_login_command_registered(self):
        command = LoginCommand(usercode="test", password="pwd")
        handler = dispatcher._command_handlers.get(command.__class__)
        self.assertIsNotNone(handler)
        self.assertIsInstance(handler, LoginCommandHandler)
