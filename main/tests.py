from django.test import TestCase

# Create your tests here.


class PwaTests(TestCase):
	def test_manifest(self):
		import json
		res = self.client.get("/manifest.webmanifest")
		self.assertEqual(res["Content-Type"].split(";")[0], "application/manifest+json")
		data = json.loads(res.content)
		self.assertEqual((data["name"], data["display"], data["start_url"]), ("MJ Gallery", "standalone", "/?source=app"))
		self.assertEqual({i["sizes"] for i in data["icons"]}, {"192x192", "512x512"})
		self.assertIn("maskable", {i["purpose"] for i in data["icons"]})
		self.assertTrue(all(s["url"].startswith("/") for s in data["shortcuts"]))

	def test_service_worker(self):
		res = self.client.get("/sw.js")
		self.assertEqual(res["Content-Type"].split(";")[0], "application/javascript")
		self.assertEqual(res["Service-Worker-Allowed"], "/")
		body = res.content.decode()
		self.assertIn("/offline/", body)
		self.assertIn('req.mode === "navigate"', body)  # 화면은 저장하지 않고 실패할 때만 안내

	def test_pages_and_head(self):
		self.assertContains(self.client.get("/offline/"), "인터넷 연결이 끊겼어요")
		self.assertContains(self.client.get("/app/"), "앱으로 설치하기")
		home = self.client.get("/")
		self.assertContains(home, 'rel="manifest"')
		self.assertContains(home, "apple-touch-icon")
		self.assertContains(home, "📱 앱으로 설치")


class ErrorPageTests(TestCase):
    """404·403 은 사이트 모양 페이지 + 관리자 메일 안내, 500 은 독립 페이지"""

    def test_404_page(self):
        from django.test import override_settings

        with override_settings(DEBUG=False):
            res = self.client.get("/this-page-does-not-exist/")
        self.assertEqual(res.status_code, 404)
        self.assertContains(res, "없는 페이지예요", status_code=404)
        self.assertContains(res, "mjseo@smjgallery.kr", status_code=404)

    def test_500_and_403_templates_render(self):
        from django.template.loader import render_to_string

        html = render_to_string("500.html")
        self.assertIn("문제가 생겼어요", html)
        self.assertIn("mjseo@smjgallery.kr", html)

    def test_footer_has_contact(self):
        res = self.client.get("/")
        self.assertContains(res, "mailto:mjseo@smjgallery.kr")


class ResumePageTests(TestCase):
    def test_resume_page_is_placeholder_not_500(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse

        admin = get_user_model().objects.create_superuser("resume-admin", "a@example.com", "pw")
        self.client.force_login(admin)
        res = self.client.get(reverse("studio:profile_resume"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "아직 준비 중인 페이지예요")


class ContactWidgetTests(TestCase):
    def test_widget_shown_for_anon_and_member_not_admin(self):
        from django.contrib.auth import get_user_model

        self.assertContains(self.client.get("/"), 'id="contact-fab"')
        User = get_user_model()
        member = User.objects.create_user("c-member", "m@example.com", "pw")
        self.client.force_login(member)
        self.assertContains(self.client.get("/"), 'id="contact-fab"')
        admin = User.objects.create_superuser("c-admin", "a@example.com", "pw")
        self.client.force_login(admin)
        self.assertNotContains(self.client.get("/"), 'id="contact-fab"')

    def test_submit_sends_mail_and_notifies(self):
        import json

        from django.core import mail
        from django.core.cache import cache
        from django.test import override_settings
        from django.urls import reverse

        from notifications.models import Notification

        cache.clear()
        url = reverse("main:contact")
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            res = self.client.post(url, json.dumps({"message": "짧"}), content_type="application/json")
            self.assertEqual(res.status_code, 400)
            res = self.client.post(url, json.dumps({"message": "사이트 오류가 있어요", "email": "bad"}), content_type="application/json")
            self.assertEqual(res.status_code, 400)
            res = self.client.post(url, json.dumps({"message": "봇입니다", "website": "x"}), content_type="application/json")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(len(mail.outbox), 0)
            res = self.client.post(url, json.dumps({"message": "가입 승인 언제 되나요?", "name": "홍길동", "email": "hong@example.com", "page": "/blog/"}), content_type="application/json")
            self.assertEqual(res.status_code, 200, res.content)
            self.assertEqual(len(mail.outbox), 1)
            sent = mail.outbox[0]
            self.assertEqual(sent.to, ["mjseo@smjgallery.kr"])
            self.assertEqual(sent.reply_to, ["hong@example.com"])
            self.assertIn("가입 승인 언제 되나요?", sent.body)
            self.assertTrue(Notification.objects.filter(title__contains="문의: 홍길동").exists())
            for _ in range(2):
                self.client.post(url, json.dumps({"message": "또 문의합니다요"}), content_type="application/json")
            res = self.client.post(url, json.dumps({"message": "네 번째 문의입니다"}), content_type="application/json")
            self.assertEqual(res.status_code, 429)
        cache.clear()
