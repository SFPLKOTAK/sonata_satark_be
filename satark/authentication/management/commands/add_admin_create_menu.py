"""
Management command to add /admin/create menu item to the database.
Run with: python manage.py add_admin_create_menu
"""
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Adds the /admin/create menu item and maps it to the Admin role (RoleId=1)'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            # Show current admin menu
            cursor.execute("""
                SELECT i.id, i.label, i.to_path, i.sort_order
                FROM [dbo].[accounts_menu_item] i
                JOIN [dbo].[accounts_role_menu_mapping] m ON i.id = m.menu_item_id
                WHERE m.role_id = 1
                ORDER BY i.sort_order
            """)
            rows = cursor.fetchall()
            self.stdout.write('Current Admin menu items:')
            for r in rows:
                self.stdout.write(f'  id={r[0]} | {r[1]} | {r[2]} | sort={r[3]}')

            # Check if already exists
            cursor.execute("SELECT id FROM [dbo].[accounts_menu_item] WHERE to_path = '/admin/create'")
            existing = cursor.fetchone()
            if existing:
                self.stdout.write(self.style.WARNING(f"/admin/create already exists (id={existing[0]})"))
                # Ensure it's mapped to admin role
                cursor.execute(
                    "SELECT COUNT(*) FROM [dbo].[accounts_role_menu_mapping] WHERE role_id=1 AND menu_item_id=%s",
                    [existing[0]]
                )
                if cursor.fetchone()[0] == 0:
                    cursor.execute(
                        "INSERT INTO [dbo].[accounts_role_menu_mapping] (role_id, menu_item_id) VALUES (1, %s)",
                        [existing[0]]
                    )
                    self.stdout.write(self.style.SUCCESS(f"Mapped existing item {existing[0]} to Admin role."))
                return

            # Get max sort_order for admin items
            cursor.execute("""
                SELECT MAX(i.sort_order)
                FROM [dbo].[accounts_menu_item] i
                JOIN [dbo].[accounts_role_menu_mapping] m ON i.id = m.menu_item_id
                WHERE m.role_id = 1
            """)
            max_sort = cursor.fetchone()[0] or 0
            new_sort = max_sort + 1

            # Insert menu item
            cursor.execute("""
                INSERT INTO [dbo].[accounts_menu_item] (label, icon, to_path, badge_text, sort_order, is_active)
                VALUES ('Create / Map', 'UserPlus', '/admin/create', NULL, %s, 1)
            """, [new_sort])

            # Get the new item ID
            cursor.execute("SELECT id FROM [dbo].[accounts_menu_item] WHERE to_path = '/admin/create'")
            new_id = cursor.fetchone()[0]
            self.stdout.write(self.style.SUCCESS(f"Inserted menu item id={new_id}, sort={new_sort}"))

            # Map to Admin role (RoleId=1)
            cursor.execute(
                "INSERT INTO [dbo].[accounts_role_menu_mapping] (role_id, menu_item_id) VALUES (1, %s)",
                [new_id]
            )
            self.stdout.write(self.style.SUCCESS(f"Mapped to Admin role (RoleId=1). DONE."))
