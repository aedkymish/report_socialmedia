from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from reports.models import ActionRequest
from reports.navigation import RequestListFilter, RequestNavigator


class RequestNavigationTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("M1", password="x")
        now = timezone.now()
        self.reqs = []
        # r0 newest ... r4 oldest; r1/r2 share the same timestamp (tie broken by pk)
        for i, (days, status) in enumerate([(0, "submitted"), (1, "approved"), (1, "submitted"),
                                            (2, "approved"), (3, "submitted")]):
            r = ActionRequest.objects.create(description=f"case {i}", monitor=self.u, uploader=self.u,
                                             created_by=self.u, status=status)
            ActionRequest.objects.filter(pk=r.pk).update(created_at=now - timedelta(days=days))
            self.reqs.append(ActionRequest.objects.get(pk=r.pk))
        self.client.force_login(self.u)

    def list_order(self, **params):
        resp = self.client.get(reverse("reports:list"), params)
        return [r.pk for r in resp.context["object_list"]]

    def walk(self, start, params=None):
        """Follow 'next' from start; return visited pks."""
        nav_filter = RequestListFilter.from_params(params or {})
        seen, cur = [], start
        while cur:
            seen.append(cur.pk)
            nxt = RequestNavigator(cur, nav_filter).next_url
            cur = ActionRequest.objects.get(pk=int(nxt.split("/")[1])) if nxt else None
        return seen

    def test_arrows_follow_the_list_order(self):
        order = self.list_order()
        first = ActionRequest.objects.get(pk=order[0])
        self.assertEqual(self.walk(first), order)
        nav = RequestNavigator(first, RequestListFilter())
        self.assertIsNone(nav.previous_url)
        self.assertEqual((nav.position, nav.total), (1, 5))
        last = RequestNavigator(ActionRequest.objects.get(pk=order[-1]), RequestListFilter())
        self.assertIsNone(last.next_url)
        self.assertEqual(last.position, 5)

    def test_previous_is_inverse_of_next(self):
        order = self.list_order()
        for a, b in zip(order, order[1:]):
            nav_b = RequestNavigator(ActionRequest.objects.get(pk=b), RequestListFilter())
            self.assertEqual(nav_b.previous_url, f"/{a}/")

    def test_filter_is_kept(self):
        params = {"status": "submitted"}
        order = self.list_order(**params)
        self.assertEqual(self.walk(ActionRequest.objects.get(pk=order[0]), params), order)
        page = self.client.get(reverse("reports:detail", args=[order[0]]), params)
        self.assertContains(page, f'href="/{order[1]}/?status=submitted" rel="next"')
        self.assertContains(page, "1 من 3")
        self.assertContains(page, 'href="/?status=submitted"')  # back to the filtered list
        lst = self.client.get(reverse("reports:list"), params).content.decode()
        self.assertIn(f'data-href="/{order[0]}/?status=submitted"', lst)

    def test_falls_back_to_full_list_when_request_left_the_filter(self):
        approved = self.reqs[1]
        nav = RequestNavigator(approved, RequestListFilter(status="submitted"))
        self.assertFalse(nav.filter.active)
        self.assertEqual(nav.total, 5)

    def test_disabled_buttons_at_the_ends(self):
        order = self.list_order()
        page = self.client.get(reverse("reports:detail", args=[order[0]])).content.decode()
        self.assertIn('aria-disabled="true"', page)
        self.assertIn('rel="next"', page)
        self.assertNotIn('rel="prev"', page)


class SearchByNumberAndPrintDateTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("M1", password="x")
        self.reqs = [ActionRequest.objects.create(description=f"case {i}", monitor=self.u, uploader=self.u,
                                                  created_by=self.u) for i in range(15)]
        self.client.force_login(self.u)

    def found(self, q):
        return [r.pk for r in self.client.get(reverse("reports:list"), {"q": q}).context["object_list"]]

    def test_search_by_request_number(self):
        target = self.reqs[11].pk
        self.assertEqual(self.found(str(target))[0], target)  # the numbered request comes first
        self.assertEqual(self.found(f"#{target}")[0], target)
        arabic = str(target).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
        self.assertEqual(self.found(arabic)[0], target)
        self.assertEqual(self.found("99999"), [])

    def test_number_search_also_matches_text(self):
        r = self.reqs[0]
        r.description = "رقم الهاتف 777"
        r.save()
        self.assertIn(r.pk, self.found("777"))

    def test_detail_title_is_clean_and_print_date_has_no_time(self):
        r = self.reqs[0]
        html = self.client.get(r.get_absolute_url()).content.decode()
        title = html[html.index("<title>"):html.index("</title>")]
        self.assertNotIn("<script", title)
        date_only = timezone.localtime(r.created_at).strftime("%Y/%m/%d")
        self.assertIn(f'<span class="print-only">{date_only}</span>', html)
