from auditlog.models import LogEntry
from django.test import TestCase
from django.urls import reverse

from accounts.models import User


class SuperadminOnlyTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser("S1", "", "pass12345")
        self.staff = User.objects.create_user("U1", password="pass12345", is_staff=True)

    def test_non_superusers_are_forbidden(self):
        self.client.force_login(self.staff)
        for name in ("accounts:list", "accounts:create", "accounts:audit"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 403, name)
        self.assertEqual(self.client.get(reverse("accounts:edit", args=[self.admin.pk])).status_code, 403)
        # Django admin is superadmin-only too, even for is_staff users
        self.assertNotEqual(self.client.get("/admin/").status_code, 200)
        self.assertNotContains(self.client.get(reverse("reports:list")), "سجل التدقيق")

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(reverse("accounts:list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])

    def test_superuser_manages_users_and_actions_are_audited(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("reports:list")), "سجل التدقيق")
        resp = self.client.post(reverse("accounts:create"), {
            "username": "M200", "full_name": "راصد", "role": "monitor", "is_active": "on",
            "password1": "Strong-pass-123", "password2": "Strong-pass-123",
        })
        self.assertRedirects(resp, reverse("accounts:list"))
        u = User.objects.get(username="M200")
        self.assertFalse(u.is_superuser)

        self.client.post(reverse("accounts:edit", args=[u.pk]), {"full_name": "راصد 2", "role": "uploader"})
        u.refresh_from_db()
        self.assertEqual((u.role, u.is_active), ("uploader", False))

        entries = LogEntry.objects.get_for_object(u)
        self.assertEqual(entries.count(), 2)
        update = entries.filter(action=LogEntry.Action.UPDATE).get()
        self.assertEqual(update.actor, self.admin)
        self.assertIn("role", update.changes_dict)
        self.assertNotIn("password", entries.filter(action=LogEntry.Action.CREATE).get().changes_dict)

        page = self.client.get(reverse("accounts:audit"), {"actor": "S1"})
        self.assertContains(page, "M200")
        self.assertContains(page, "راصد 2")

    def test_cannot_demote_or_disable_self(self):
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("accounts:edit", args=[self.admin.pk]), {"full_name": "x", "role": "approver"})
        self.assertContains(resp, "لا يمكنك تعطيل حسابك")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_superuser and self.admin.is_active)

    def test_set_password(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("accounts:password", args=[self.staff.pk]),
                         {"new_password1": "Another-pass-99", "new_password2": "Another-pass-99"})
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.check_password("Another-pass-99"))
