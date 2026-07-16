import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'satark.settings')
django.setup()

from unittest import TestCase
from satark.cqrs import Command, Query, CommandHandler, QueryHandler, CQRSDispatcher

class DummyCommand(Command):
    def __init__(self, value):
        self.value = value

class DummyCommandHandler(CommandHandler):
    def execute(self, command: DummyCommand):
        return f"Executed command with value: {command.value}"

class DummyQuery(Query):
    def __init__(self, param):
        self.param = param

class DummyQueryHandler(QueryHandler):
    def execute(self, query: DummyQuery):
        return f"Returned query with param: {query.param}"

class CQRSTests(TestCase):
    def test_cqrs_dispatcher_command(self):
        dispatcher = CQRSDispatcher()
        dispatcher.register_command(DummyCommand, DummyCommandHandler())
        
        command = DummyCommand("TestValue")
        result = dispatcher.send(command)
        
        self.assertEqual(result, "Executed command with value: TestValue")

    def test_cqrs_dispatcher_query(self):
        dispatcher = CQRSDispatcher()
        dispatcher.register_query(DummyQuery, DummyQueryHandler())
        
        query = DummyQuery("TestParam")
        result = dispatcher.query(query)
        
        self.assertEqual(result, "Returned query with param: TestParam")

    def test_unregistered_command_raises_error(self):
        dispatcher = CQRSDispatcher()
        with self.assertRaises(ValueError):
            dispatcher.send(DummyCommand("Oops"))

    def test_unregistered_query_raises_error(self):
        dispatcher = CQRSDispatcher()
        with self.assertRaises(ValueError):
            dispatcher.query(DummyQuery("Oops"))
