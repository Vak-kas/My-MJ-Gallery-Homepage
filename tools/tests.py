from django.test import TestCase
from django.urls import reverse

from .registry import TOOLS


class ToolPagesTests(TestCase):
	def test_hub_lists_every_registered_tool(self):
		resp = self.client.get(reverse("tools:index"))
		self.assertEqual(resp.status_code, 200)
		for tool in TOOLS:
			self.assertContains(resp, tool["title"])
			self.assertContains(resp, reverse(tool["url_name"]))

	def test_tool_pages_are_public(self):
		for tool in TOOLS:
			self.assertEqual(self.client.get(reverse(tool["url_name"])).status_code, 200)

	def test_nav_has_tool_link(self):
		resp = self.client.get(reverse("tools:index"))
		self.assertContains(resp, f'href="{reverse("tools:index")}"')

	def test_home_quick_nav_has_tool_link(self):
		resp = self.client.get(reverse("main:home"))
		self.assertContains(resp, f'href="{reverse("tools:index")}"')


class SpeedtestApiTests(TestCase):
	def setUp(self):
		from django.core.cache import cache
		cache.clear()

	def test_ping_is_tiny_and_uncached(self):
		resp = self.client.get(reverse("tools:speedtest_ping"))
		self.assertEqual(resp.status_code, 200)
		self.assertIn("no-store", resp["Cache-Control"])

	def test_download_streams_requested_bytes_with_cap(self):
		resp = self.client.get(reverse("tools:speedtest_download"), {"bytes": 3 * 1024 * 1024 + 5})
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(len(b"".join(resp.streaming_content)), 3 * 1024 * 1024 + 5)
		huge = self.client.get(reverse("tools:speedtest_download"), {"bytes": 10 ** 12})
		self.assertEqual(int(huge["Content-Length"]), 25 * 1024 * 1024)

	def test_upload_counts_bytes_without_csrf(self):
		from django.test import Client
		client = Client(enforce_csrf_checks=True)
		resp = client.post(reverse("tools:speedtest_upload"), data=b"x" * 12345, content_type="application/octet-stream")
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.json()["received"], 12345)

	def test_upload_rejects_oversized_and_empty(self):
		url = reverse("tools:speedtest_upload")
		self.assertEqual(self.client.post(url, data=b"", content_type="application/octet-stream").status_code, 400)
		self.assertEqual(self.client.generic("POST", url, b"x", CONTENT_LENGTH=str(26 * 1024 * 1024)).status_code, 413)

	def test_quota_per_ip(self):
		url = reverse("tools:speedtest_download")
		size = 25 * 1024 * 1024
		# 다운로드 한도 1GB / 10분 → 25MB 요청 40번까지 허용
		statuses = [self.client.get(url, {"bytes": size}, HTTP_X_REAL_IP="1.2.3.4").status_code for _ in range(41)]
		self.assertEqual(statuses[:40], [200] * 40)
		self.assertEqual(statuses[40], 429)
		# 다른 IP 는 영향 없음
		self.assertEqual(self.client.get(url, {"bytes": size}, HTTP_X_REAL_IP="5.6.7.8").status_code, 200)

	def test_speedtest_page_is_public(self):
		self.assertEqual(self.client.get(reverse("tools:speedtest")).status_code, 200)
