import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'satark.settings')
django.setup()

from unittest import TestCase
from satark.cqrs import dispatcher
from . import views
from .queries import GetReportTypesQuery, GetReportTypesQueryHandler
from .commands import CreateChecklistPointCommand, CreateChecklistPointCommandHandler

class AuditCQRSTests(TestCase):
    def test_get_report_types_query_registered(self):
        query = GetReportTypesQuery()
        handler = dispatcher._query_handlers.get(query.__class__)
        self.assertIsNotNone(handler)
        self.assertIsInstance(handler, GetReportTypesQueryHandler)

    def test_create_checklist_point_command_registered(self):
        command = CreateChecklistPointCommand(
            report_type="Branch Audit",
            section_code="SEC_01",
            section_name="Center Discipline",
            section_weight_pct=10.0,
            section_display_order=1,
            intent_title="Is layout correct?",
            intent_description="Check layout",
            category="Critical",
            max_score=10,
            accepted_deviation_pct=0.0
        )
        handler = dispatcher._command_handlers.get(command.__class__)
        self.assertIsNotNone(handler)
        self.assertIsInstance(handler, CreateChecklistPointCommandHandler)
