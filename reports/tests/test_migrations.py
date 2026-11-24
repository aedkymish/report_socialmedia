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


class NormalizedUrlBackfillTests(TransactionTestCase):
    before = [("reports", "0004_link_request_verbose_name"), ("accounts", "0002_remove_platform_contact_role")]
    after = [("reports", "0005_link_normalized_url")]

    def test_existing_links_get_normalized_url(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        old = executor.loader.project_state(self.before).apps
        User = old.get_model("accounts", "User")
        Req = old.get_model("reports", "ActionRequest")
        Link = old.get_model("reports", "RequestLink")
        u = User.objects.create(username="M1")
        r = Req.objects.create(description="d", monitor=u, uploader=u, created_by=u)
        link = Link.objects.create(request=r, url="https://www.TikTok.com/@A/video/1/?lang=ar")

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        new = executor.loader.project_state(self.after).apps
        self.assertEqual(new.get_model("reports", "RequestLink").objects.get(pk=link.pk).normalized_url,
                         "tiktok.com/@a/video/1")
        MigrationExecutor(connection).migrate(executor.loader.graph.leaf_nodes())
