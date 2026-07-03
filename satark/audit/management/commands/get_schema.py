from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            # list tables matching 'audit%'
            cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME LIKE 'audit%'")
            tables = [r[0] for r in cursor.fetchall()]
            
            for t in tables:
                if 'check' in t or 'feedback' in t or 'trn' in t or 'score' in t:
                    cursor.execute(f"SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = '{t}'")
                    cols = [r[0] for r in cursor.fetchall()]
                    print(f"{t}: {cols}")
