from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from blog.models import Comment, GuestbookEntry, Post


class ModerationTestBase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser("admin", "a@example.com", "pw")
        self.spammer = User.objects.create_user("spammer", "s@example.com", "pw")
        self.member = User.objects.create_user("member", "m@example.com", "pw")
        self.client.force_login(self.admin)
        self.good = self.post("정상 글", self.member)

    def post(self, title, author, **kw):
        n = Post.objects.count()
        return Post.objects.create(category="tech", title=title, slug=f"p{n}", author=author,
                                   published_at=timezone.now(), **kw)


class PostsBulkTests(ModerationTestBase):
    def test_title_filter_and_filtered_scope_delete(self):
        for i in range(25):  # 한 페이지(20개)를 넘겨도 전부 지워지는지
            self.post(f"광고 555 {i}", self.spammer)
        res = self.client.get(reverse("studio:posts"), {"title_q": "555"})
        self.assertEqual(res.context["post_count"], 25)

        self.client.post(reverse("studio:posts"), {
            "bulk_action": "delete", "bulk_scope": "filtered", "bulk_delete_confirm": "DELETE",
            "return_qs": urlencode({"title_q": "555"}),
        })
        self.assertEqual(Post.objects.count(), 1)
        self.assertTrue(Post.objects.filter(id=self.good.id).exists())

    def test_filtered_scope_requires_filter(self):
        self.client.post(reverse("studio:posts"), {
            "bulk_action": "delete", "bulk_scope": "filtered", "bulk_delete_confirm": "DELETE", "return_qs": "",
        })
        self.assertTrue(Post.objects.filter(id=self.good.id).exists())

    def test_unpublish_keeps_published_at(self):
        before = self.good.published_at
        self.client.post(reverse("studio:posts"), {"bulk_action": "unpublish", "selected_ids": [self.good.id]})
        self.good.refresh_from_db()
        self.assertFalse(self.good.is_published)
        self.assertEqual(self.good.published_at, before)


class CommunityTests(ModerationTestBase):
    def setUp(self):
        super().setUp()
        self.g_spam = GuestbookEntry.objects.create(author_name="spam", message="555 카지노")
        self.g_ok = GuestbookEntry.objects.create(author=self.member, author_name="member", message="안녕하세요")
        self.c_spam = Comment.objects.create(post=self.good, author=self.spammer, author_name="spammer", content="555 링크")

    def test_requires_superuser(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("studio:community")).status_code, 302)
        self.assertEqual(self.client.get(reverse("studio:users")).status_code, 302)

    def test_list_and_hide(self):
        res = self.client.get(reverse("studio:community"), {"tab": "guestbook", "q": "555"})
        self.assertEqual(res.context["item_count"], 1)
        self.client.post(reverse("studio:community"), {
            "action": "hide", "ids": [self.g_spam.id], "return_qs": "tab=guestbook",
        })
        self.g_spam.refresh_from_db()
        self.assertFalse(self.g_spam.is_visible)

    def test_filtered_delete_needs_confirm(self):
        data = {"action": "delete", "scope": "filtered", "return_qs": "tab=guestbook&q=555"}
        self.client.post(reverse("studio:community"), data)
        self.assertTrue(GuestbookEntry.objects.filter(id=self.g_spam.id).exists())
        self.client.post(reverse("studio:community"), {**data, "confirm": "DELETE"})
        self.assertFalse(GuestbookEntry.objects.filter(id=self.g_spam.id).exists())
        self.assertTrue(GuestbookEntry.objects.filter(id=self.g_ok.id).exists())

    def test_keyword_purge_preview_and_delete(self):
        spam_post = self.post("555 이벤트", self.spammer)
        qs = urlencode([("tab", "cleanup"), ("keyword", "555"), ("fields", "post_title"),
                        ("fields", "comments"), ("fields", "guestbook")])
        res = self.client.get(reverse("studio:community") + "?" + qs)
        self.assertEqual(res.context["preview_total"], 3)
        self.client.post(reverse("studio:community"), {"action": "purge", "confirm": "DELETE", "return_qs": qs})
        self.assertFalse(Post.objects.filter(id=spam_post.id).exists())
        self.assertFalse(Comment.objects.exists())
        self.assertEqual(list(GuestbookEntry.objects.all()), [self.g_ok])
        self.assertTrue(Post.objects.filter(id=self.good.id).exists())


class UsersTests(ModerationTestBase):
    def test_list_counts(self):
        self.post("스팸", self.spammer)
        res = self.client.get(reverse("studio:users"), {"q": "spam"})
        [u] = res.context["users"]
        self.assertEqual((u.username, u.post_count), ("spammer", 1))

    def test_suspend_and_activate(self):
        self.client.post(reverse("studio:users"), {"action": "suspend", "ids": [self.spammer.id]})
        self.spammer.refresh_from_db()
        self.assertFalse(self.spammer.is_active)
        res = self.client.get(reverse("studio:users"), {"state": "inactive"})
        self.assertEqual([u.username for u in res.context["users"]], ["spammer"])
        self.client.post(reverse("studio:users"), {"action": "activate", "ids": [self.spammer.id]})
        self.spammer.refresh_from_db()
        self.assertTrue(self.spammer.is_active)

    def test_purge_content(self):
        self.post("스팸", self.spammer)
        Comment.objects.create(post=self.good, author=self.spammer, author_name="spammer", content="x")
        GuestbookEntry.objects.create(author=self.spammer, author_name="spammer", message="x")
        self.client.post(reverse("studio:users"), {"action": "purge", "ids": [self.spammer.id], "confirm": "DELETE"})
        self.spammer.refresh_from_db()
        self.assertFalse(self.spammer.is_active)
        self.assertFalse(Post.objects.filter(author=self.spammer).exists())
        self.assertFalse(Comment.objects.filter(author=self.spammer).exists())
        self.assertFalse(GuestbookEntry.objects.filter(author=self.spammer).exists())
        self.assertTrue(Post.objects.filter(id=self.good.id).exists())

    def test_delete_account(self):
        self.client.post(reverse("studio:users"), {"action": "delete", "ids": [self.spammer.id]})
        self.assertTrue(get_user_model().objects.filter(id=self.spammer.id).exists())  # 확인 문구 없으면 안 지움
        self.client.post(reverse("studio:users"), {"action": "delete", "ids": [self.spammer.id], "confirm": "DELETE"})
        self.assertFalse(get_user_model().objects.filter(id=self.spammer.id).exists())

    def test_cannot_touch_self_or_admin(self):
        other_admin = get_user_model().objects.create_superuser("admin2", "b@example.com", "pw")
        self.client.post(reverse("studio:users"), {"action": "suspend", "ids": [self.admin.id, other_admin.id]})
        self.admin.refresh_from_db()
        other_admin.refresh_from_db()
        self.assertTrue(self.admin.is_active and other_admin.is_active)


class CommunityShortLinkTests(ModerationTestBase):
    def setUp(self):
        super().setUp()
        from tools.models import ShortLink
        self.phish = ShortLink.objects.create(code="bad001", target_url="https://evil-login.example/kakao", owner=self.spammer)
        self.phish2 = ShortLink.objects.create(code="bad002", target_url="https://evil-login.example/naver", owner=self.spammer)
        self.ok = ShortLink.objects.create(code="good01", target_url="https://github.com/", owner=self.member)

    def test_list_and_filter(self):
        res = self.client.get(reverse("studio:community"), {"tab": "links", "q": "evil-login"})
        self.assertEqual(res.context["item_count"], 2)
        self.assertContains(res, "/s/bad001")
        res = self.client.get(reverse("studio:community"), {"tab": "links", "owner": "member"})
        self.assertEqual([l.code for l in res.context["items"]], ["good01"])

    def test_delete_filtered_needs_confirm(self):
        from tools.models import ShortLink
        data = {"action": "delete", "scope": "filtered", "return_qs": "tab=links&q=evil-login"}
        self.client.post(reverse("studio:community"), data)
        self.assertEqual(ShortLink.objects.count(), 3)
        self.client.post(reverse("studio:community"), {**data, "confirm": "DELETE"})
        self.assertEqual(list(ShortLink.objects.values_list("code", flat=True)), ["good01"])

    def test_keyword_purge_includes_links(self):
        from tools.models import ShortLink
        qs = urlencode([("tab", "cleanup"), ("keyword", "evil-login"), ("fields", "links")])
        res = self.client.get(reverse("studio:community") + "?" + qs)
        self.assertEqual(res.context["preview_total"], 2)
        self.client.post(reverse("studio:community"), {"action": "purge", "confirm": "DELETE", "return_qs": qs})
        self.assertEqual(ShortLink.objects.count(), 1)

    def test_user_purge_removes_links(self):
        from tools.models import ShortLink
        self.client.post(reverse("studio:users"), {"action": "purge", "ids": [self.spammer.id], "confirm": "DELETE"})
        self.assertFalse(ShortLink.objects.filter(owner=self.spammer).exists())
        self.assertTrue(ShortLink.objects.filter(code="good01").exists())


class SiteSettingsTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        User = get_user_model()
        self.admin = User.objects.create_superuser("admin", "a@example.com", "pw")
        self.member = User.objects.create_user("member", "m@example.com", "pw")

    def tearDown(self):
        from django.core.cache import cache
        cache.clear()  # 설정 캐시가 다른 테스트로 새지 않게

    def save(self, nav=None, home=None, **extra):
        nav = nav or ["home", "blog", "tool", "photo"]
        home = home or ["profile", "skill", "career", "activity", "award", "publication", "project", "blog_links"]
        data = {"nav_order": nav, "home_order": home, **{f"home_on_{k}": "on" for k in home}}
        data.update(extra)
        self.client.force_login(self.admin)
        return self.client.post(reverse("studio:settings"), data)

    def nav_labels(self, path="/blog/"):
        return [i["label"] for i in self.client.get(path).context["site_nav"]]

    def test_defaults_and_member_cannot_open(self):
        self.assertEqual(self.nav_labels(), ["Home", "Blog", "Tool", "Gallery"])
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("studio:settings")).status_code, 302)

    def test_reorder_and_rename(self):
        self.save(nav=["home", "photo", "tool", "blog"], nav_label_photo="사진")
        self.client.logout()
        self.assertEqual(self.nav_labels("/tools/"), ["Home", "사진", "Tool", "Blog"])

    def test_hidden_section_blocks_page_but_not_share_links(self):
        self.save(nav_state_tool="admin", nav_state_photo="members")
        self.client.logout()
        self.assertEqual(self.nav_labels(), ["Home", "Blog"])
        self.assertEqual(self.client.get("/tools/").status_code, 404)
        self.assertEqual(self.client.get("/tools/keygen/").status_code, 404)
        self.assertEqual(self.client.get("/tools/secret/abc/").status_code, 404)  # 숨김이면 공유 링크도 막힘
        resp = self.client.get(reverse("main:photos"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("accounts:login"), resp["Location"])
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("main:photos")).status_code, 200)
        self.assertEqual(self.client.get("/tools/").status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/tools/").status_code, 200)
        self.assertIn("Tool", self.nav_labels())

    def test_members_only_keeps_share_links_open(self):
        self.save(nav_state_tool="members")
        self.client.logout()
        self.assertEqual(self.client.get("/tools/").status_code, 302)
        self.assertEqual(self.client.get("/tools/secret/abc/").status_code, 200)

    def test_admin_sees_hidden_home_sections(self):
        order = ["profile", "skill", "career", "activity", "award", "publication", "project", "blog_links"]
        data = {"nav_order": ["home", "blog", "tool", "photo"], "home_order": order, "nav_state_blog": "admin",
                **{f"home_on_{k}": "on" for k in order if k != "award"}}
        self.client.force_login(self.admin)
        self.client.post(reverse("studio:settings"), data)
        res = self.client.get("/")
        sections = {s["key"]: s["hidden"] for s in res.context["home_sections"]}
        self.assertTrue(sections["award"])
        self.assertIn("blog_links", sections)
        self.assertContains(res, "관리자에게만 보여요")
        self.client.force_login(self.member)
        keys = [s["key"] for s in self.client.get("/").context["home_sections"]]
        self.assertNotIn("award", keys)
        self.assertNotIn("blog_links", keys)

    def test_home_cannot_be_hidden(self):
        self.save(nav_state_home="admin")
        self.client.logout()
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertIn("Home", self.nav_labels())

    def test_home_sections_order_and_toggle(self):
        order = ["project", "profile", "skill", "career", "activity", "award", "publication", "blog_links"]
        data = {"nav_order": ["home", "blog", "tool", "photo"], "home_order": order,
                **{f"home_on_{k}": "on" for k in order if k not in ("award", "publication")}}
        self.client.force_login(self.admin)
        self.client.post(reverse("studio:settings"), data)
        self.client.logout()
        keys = [s["key"] for s in self.client.get("/").context["home_sections"]]
        self.assertEqual(keys, ["project", "profile", "skill", "career", "activity", "blog_links"])

    def test_blog_links_hidden_when_blog_closed(self):
        self.save(nav_state_blog="members")
        self.client.logout()
        keys = [s["key"] for s in self.client.get("/").context["home_sections"]]
        self.assertNotIn("blog_links", keys)
        self.assertEqual(self.client.get("/blog/").status_code, 302)

    def test_tampered_post_rejected(self):
        self.save(nav=["home", "blog"])  # 항목 누락
        self.assertEqual(self.nav_labels(), ["Home", "Blog", "Tool", "Gallery"])
