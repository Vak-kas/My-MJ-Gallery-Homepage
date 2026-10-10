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
