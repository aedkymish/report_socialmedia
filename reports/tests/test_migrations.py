from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings


@override_settings(PLATFORM_CONTACT_CODE="003")
class PlatformContactMigrationTests(TransactionTestCase):
    """0003: platform_contact FK -> fixed code; old requests keep their code."""

    before = [("reports", "0002_profile_videos_image"), ("accounts", "0001_initial")]
    after = [("reports", "0003_platform_contact_code"), ("accounts", "0002_remove_platform_contact_role")]

    def test_codes_copied_and_contact_users_become_monitors(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        old = executor.loader.project_state(self.before).apps
        User = old.get_model("accounts", "User")
        Req = old.get_model("reports", "ActionRequest")
        m = User.objects.create(username="M100", role="monitor")
        pc = User.objects.create(username="P300", role="platform_contact")
        req = Req.objects.create(description="old", monitor=m, uploader=m, platform_contact=pc, created_by=m)

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        new = executor.loader.project_state(self.after).apps
        self.assertEqual(new.get_model("reports", "ActionRequest").objects.get(pk=req.pk).platform_contact_code, "P300")
        self.assertEqual(new.get_model("accounts", "User").objects.get(username="P300").role, "monitor")

        MigrationExecutor(connection).migrate(executor.loader.graph.leaf_nodes())  # back to latest
