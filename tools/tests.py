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
		# 다운로드 한도 2GB / 10분 → 25MB 요청 81번까지 허용
		statuses = [self.client.get(url, {"bytes": size}, HTTP_X_REAL_IP="1.2.3.4").status_code for _ in range(82)]
		self.assertEqual(statuses[:81], [200] * 81)
		self.assertEqual(statuses[81], 429)
		blocked = self.client.get(url, {"bytes": size}, HTTP_X_REAL_IP="1.2.3.4")
		self.assertIn("분 뒤", blocked.json()["error"])
		self.assertGreater(int(blocked["Retry-After"]), 0)
		# 다른 IP 는 영향 없음
		self.assertEqual(self.client.get(url, {"bytes": size}, HTTP_X_REAL_IP="5.6.7.8").status_code, 200)

	def test_quota_window_is_fixed_from_first_request(self):
		from unittest import mock
		url = reverse("tools:speedtest_download")
		size = 25 * 1024 * 1024
		with mock.patch("tools.speedtest.time.time", return_value=1000.0):
			for _ in range(81):
				self.client.get(url, {"bytes": size}, HTTP_X_REAL_IP="9.9.9.9")
		# 첫 요청 9분 59초 뒤: 아직 막힘
		with mock.patch("tools.speedtest.time.time", return_value=1000.0 + 599):
			self.assertEqual(self.client.get(url, {"bytes": size}, HTTP_X_REAL_IP="9.9.9.9").status_code, 429)
		# 첫 요청 10분 뒤: 막힌 동안 요청을 계속 보냈어도 풀림
		with mock.patch("tools.speedtest.time.time", return_value=1000.0 + 600):
			self.assertEqual(self.client.get(url, {"bytes": size}, HTTP_X_REAL_IP="9.9.9.9").status_code, 200)

	def test_superuser_has_no_quota(self):
		from django.contrib.auth import get_user_model
		admin = get_user_model().objects.create_superuser("admin", "admin@example.com", "pw-for-tests-only")
		self.client.force_login(admin)
		url = reverse("tools:speedtest_download")
		size = 25 * 1024 * 1024
		statuses = {self.client.get(url, {"bytes": size}, HTTP_X_REAL_IP="1.2.3.4").status_code for _ in range(90)}
		self.assertEqual(statuses, {200})

	def test_speedtest_page_is_public(self):
		self.assertEqual(self.client.get(reverse("tools:speedtest")).status_code, 200)
