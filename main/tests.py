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
