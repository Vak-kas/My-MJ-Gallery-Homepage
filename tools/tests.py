from django.test import TestCase
from django.urls import reverse

from .registry import TOOLS


class ToolPagesTests(TestCase):
	def test_hub_lists_every_registered_tool(self):
		resp = self.client.get(reverse("tools:index"))
		self.assertEqual(resp.status_code, 200)
		for tool in TOOLS:
			if tool.get("admin_only"):
				self.assertNotContains(resp, tool["title"])
				continue
			self.assertContains(resp, tool["title"])
			self.assertContains(resp, reverse(tool["url_name"]))

	def test_tool_pages_are_public(self):
		for tool in TOOLS:
			if tool.get("admin_only") or tool.get("login_required"):
				continue
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


class StreamViewTests(TestCase):
	ROOM = {
		"id": "abc123", "token": "secret-token", "sender_token": "send-token", "receiver_token": "recv-token", "kind": "iq",
		"meta": {"format": "sc8", "sample_rate": 2000000.0, "center_freq": 433920000.0, "label": "연구실"},
		"allow_ips": ["203.0.113.5/32"], "in_port": 5550, "out_port": 5551, "out_socket": "PUB",
		"rate_limit": 16 * 1024 * 1024, "total_limit": 20 * 1024 ** 3, "created_at": 0, "expires_at": 0, "expires_in": 3600,
		"joined": {"sender": [], "receiver": []},
		"stats": {"bytes_in": 0, "bytes_dropped": 0, "messages": 0, "rate_bps": 0, "senders": 0, "receivers": 0, "viewers": 0, "idle_seconds": None, "file": None, "closed": None},
	}

	def setUp(self):
		from django.contrib.auth import get_user_model
		User = get_user_model()
		self.admin = User.objects.create_superuser("admin", "admin@example.com", "pw-for-tests-only")
		self.member = User.objects.create_user("member", "member@example.com", "pw-for-tests-only")

	def test_anonymous_is_sent_to_login_and_member_is_forbidden(self):
		resp = self.client.get(reverse("tools:stream"))
		self.assertEqual(resp.status_code, 302)
		self.assertIn(reverse("accounts:login"), resp["Location"])
		self.client.force_login(self.member)
		self.assertEqual(self.client.get(reverse("tools:stream")).status_code, 403)
		self.assertEqual(self.client.post(reverse("tools:stream"), {"kind": "iq"}).status_code, 403)

	def test_hub_shows_stream_card_only_to_admin(self):
		self.assertNotContains(self.client.get(reverse("tools:index")), "데이터 전송")
		self.client.force_login(self.admin)
		self.assertContains(self.client.get(reverse("tools:index")), "데이터 전송")

	def test_admin_creates_room_with_parsed_options(self):
		from unittest import mock
		self.client.force_login(self.admin)
		with mock.patch("tools.relay_client.create_room", return_value=self.ROOM) as create:
			resp = self.client.post(reverse("tools:stream"), {
				"kind": "iq", "format": "sc8", "sample_rate": "2000000", "center_freq": "433920000",
				"label": "연구실", "allow_ips": "203.0.113.5\n10.0.0.0/8", "ttl_minutes": "30", "rate_mb": "8", "total_gb": "1",
			})
		payload = create.call_args.args[0]
		self.assertEqual(payload["kind"], "iq")
		self.assertEqual(payload["meta"]["format"], "sc8")
		self.assertEqual(payload["allow_ips"], ["203.0.113.5", "10.0.0.0/8"])
		self.assertEqual(payload["ttl"], 1800)
		self.assertEqual(payload["rate_limit"], 8 * 1024 * 1024)
		self.assertEqual(payload["total_limit"], 1024 ** 3)
		self.assertEqual(resp["Location"], f"{reverse('tools:stream_room', args=['abc123'])}?token=secret-token")

	def test_list_shows_friendly_error_when_relay_is_down(self):
		self.client.force_login(self.admin)
		with self.settings(RELAY_API_URL="http://127.0.0.1:1", RELAY_API_KEY="k"):
			resp = self.client.get(reverse("tools:stream"))
		self.assertContains(resp, "mj-relay")

	def _room_json(self, resp):
		return resp.content.decode().split('id="sr-room" type="application/json">')[1].split("</script>")[0]

	def test_room_page_needs_valid_token(self):
		from unittest import mock
		with mock.patch("tools.relay_client.get_room", return_value=self.ROOM):
			self.assertEqual(self.client.get(reverse("tools:stream_room", args=["abc123"])).status_code, 404)
			self.assertEqual(self.client.get(reverse("tools:stream_room", args=["abc123"]), {"token": "wrong"}).status_code, 404)

	def test_admin_link_shows_both_role_links_without_joining(self):
		from unittest import mock
		self.client.force_login(self.admin)
		with mock.patch("tools.relay_client.get_room", return_value=self.ROOM), mock.patch("tools.relay_client.join_room") as join:
			resp = self.client.get(reverse("tools:stream_room", args=["abc123"]), {"token": "secret-token"})
		join.assert_not_called()
		self.assertContains(resp, "?token=send-token")
		self.assertContains(resp, "?token=recv-token")
		self.assertContains(resp, "방 닫기")
		for secret in ("secret-token", "send-token", "recv-token"):
			self.assertNotIn(secret, self._room_json(resp))

	def test_sender_link_registers_ip_and_shows_only_sender_side(self):
		from unittest import mock
		with mock.patch("tools.relay_client.get_room", return_value=self.ROOM), mock.patch("tools.relay_client.join_room", return_value=self.ROOM) as join:
			resp = self.client.get(reverse("tools:stream_room", args=["abc123"]), {"token": "send-token"}, HTTP_X_REAL_IP="198.51.100.7")
		join.assert_called_once_with("abc123", "sender", "send-token", "198.51.100.7")
		self.assertContains(resp, "198.51.100.7")
		self.assertContains(resp, "ZMQ PUSH Sink")
		self.assertNotContains(resp, "ZMQ SUB Source")
		self.assertNotContains(resp, "recv-token")
		self.assertNotContains(resp, "방 닫기")

	def test_receiver_link_registers_as_receiver(self):
		from unittest import mock
		with mock.patch("tools.relay_client.get_room", return_value=self.ROOM), mock.patch("tools.relay_client.join_room", return_value=self.ROOM) as join:
			resp = self.client.get(reverse("tools:stream_room", args=["abc123"]), {"token": "recv-token"}, HTTP_X_REAL_IP="198.51.100.8")
		join.assert_called_once_with("abc123", "receiver", "recv-token", "198.51.100.8")
		self.assertContains(resp, "ZMQ SUB Source")
		self.assertNotContains(resp, "ZMQ PUSH Sink")
		self.assertNotContains(resp, "send-token")

	def test_join_heartbeat_uses_token_role(self):
		from unittest import mock
		url = reverse("tools:stream_join", args=["abc123"])
		with mock.patch("tools.relay_client.get_room", return_value=self.ROOM), mock.patch("tools.relay_client.join_room") as join:
			resp = self.client.post(f"{url}?token=recv-token&role=sender", HTTP_X_REAL_IP="198.51.100.9")
			self.assertEqual(resp.json(), {"role": "receiver", "ip": "198.51.100.9"})  # 토큰 역할이 우선
			resp = self.client.post(f"{url}?token=secret-token&role=sender", HTTP_X_REAL_IP="198.51.100.10")
			self.assertEqual(resp.json()["role"], "sender")  # 관리자는 역할 선택 가능
			self.assertEqual(self.client.post(f"{url}?token=nope").status_code, 404)
		self.assertEqual(join.call_count, 2)

	def test_only_admin_can_close(self):
		from unittest import mock
		with mock.patch("tools.relay_client.close_room") as close:
			self.client.force_login(self.member)
			self.assertEqual(self.client.post(reverse("tools:stream_close", args=["abc123"])).status_code, 403)
			self.client.force_login(self.admin)
			self.client.post(reverse("tools:stream_close", args=["abc123"]))
		close.assert_called_once_with("abc123")


import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

_PRIVATE = tempfile.mkdtemp(prefix="mj-private-test-")


@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE)
class ClipboardTests(TestCase):
	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()
		shutil.rmtree(_PRIVATE, ignore_errors=True)

	def setUp(self):
		from django.contrib.auth import get_user_model
		User = get_user_model()
		self.alice = User.objects.create_user("alice", "a@example.com", "pw-for-tests-only")
		self.bob = User.objects.create_user("bob", "b@example.com", "pw-for-tests-only")
		self.client.force_login(self.alice)

	def add_text(self, text="hello"):
		return self.client.post(reverse("tools:clipboard_add"), {"text": text})

	def add_file(self, name="pic.png", content=b"\x89PNG fake", mime="image/png"):
		return self.client.post(reverse("tools:clipboard_add"), {"file": SimpleUploadedFile(name, content, content_type=mime)})

	def test_requires_login(self):
		self.client.logout()
		for name in ("tools:clipboard", "tools:clipboard_list"):
			resp = self.client.get(reverse(name))
			self.assertEqual(resp.status_code, 302)
			self.assertIn(reverse("accounts:login"), resp["Location"])

	def test_text_image_file_round_trip(self):
		self.assertEqual(self.add_text("복사할 글").status_code, 201)
		img = self.add_file().json()["item"]
		doc = self.add_file("report.pdf", b"%PDF-1.4 data", "application/pdf").json()["item"]
		self.assertEqual(img["kind"], "image")
		self.assertEqual(doc["kind"], "file")
		data = self.client.get(reverse("tools:clipboard_list")).json()
		self.assertEqual([i["kind"] for i in data["items"]], ["file", "image", "text"])
		self.assertEqual(data["items"][2]["text"], "복사할 글")
		resp = self.client.get(doc["url"])
		self.assertEqual(b"".join(resp.streaming_content), b"%PDF-1.4 data")
		self.assertIn("attachment", resp["Content-Disposition"])
		inline = self.client.get(img["url"] + "?inline=1")
		self.assertNotIn("attachment", inline["Content-Disposition"])

	def test_items_are_private_per_user(self):
		item = self.add_file().json()["item"]
		self.add_text("alice secret")
		self.client.force_login(self.bob)
		self.assertEqual(self.client.get(reverse("tools:clipboard_list")).json()["items"], [])
		self.assertEqual(self.client.get(item["url"]).status_code, 404)
		self.assertEqual(self.client.post(reverse("tools:clipboard_delete", args=[item["id"]])).status_code, 404)

	def test_files_are_not_in_public_media(self):
		from django.conf import settings
		from tools.models import ClipItem
		self.add_file()
		path = ClipItem.objects.get().file.path
		self.assertTrue(path.startswith(str(_PRIVATE)))
		self.assertFalse(path.startswith(str(settings.MEDIA_ROOT)))

	def test_version_detects_changes(self):
		first = self.client.get(reverse("tools:clipboard_list")).json()
		same = self.client.get(reverse("tools:clipboard_list"), {"since": first["version"]}).json()
		self.assertTrue(same["unchanged"])
		self.add_text()
		changed = self.client.get(reverse("tools:clipboard_list"), {"since": first["version"]}).json()
		self.assertNotIn("unchanged", changed)
		self.assertEqual(len(changed["items"]), 1)

	def test_pin_delete_and_clear_keep_pinned(self):
		from tools.models import ClipItem
		keep = self.add_text("keep").json()["item"]
		self.add_text("drop")
		file_item = self.add_file().json()["item"]
		self.client.post(reverse("tools:clipboard_pin", args=[keep["id"]]))
		path = ClipItem.objects.get(pk=file_item["id"]).file.path
		resp = self.client.post(reverse("tools:clipboard_clear"))
		self.assertEqual(resp.json()["deleted"], 2)
		self.assertEqual(list(ClipItem.objects.values_list("text", flat=True)), ["keep"])
		import os
		self.assertFalse(os.path.exists(path))  # 파일도 지워짐

	def test_limits(self):
		from unittest import mock
		self.assertEqual(self.add_text("   ").status_code, 400)
		with mock.patch("tools.clipboard_views.MAX_TEXT_CHARS", 5):
			self.assertEqual(self.add_text("123456").status_code, 400)
		with mock.patch("tools.clipboard_views.MAX_FILE_BYTES", 4):
			self.assertEqual(self.add_file(content=b"12345").status_code, 400)
		with mock.patch("tools.clipboard_views.MAX_USER_ITEMS", 1):
			self.add_text("one")
			self.assertEqual(self.add_text("two").status_code, 400)

	def test_hub_card_visible_and_page_renders(self):
		self.assertContains(self.client.get(reverse("tools:index")), "내 클립보드")
		self.assertContains(self.client.get(reverse("tools:clipboard")), "alice")


@override_settings(PRIVATE_MEDIA_ROOT=_PRIVATE)
class ShareTests(TestCase):
	def setUp(self):
		from django.contrib.auth import get_user_model
		User = get_user_model()
		self.admin = User.objects.create_superuser("admin", "admin@example.com", "pw-for-tests-only")
		self.member = User.objects.create_user("member", "m@example.com", "pw-for-tests-only")

	def create(self, size, **extra):
		import json
		return self.client.post(reverse("tools:share_create"), json.dumps({"name": "data.bin", "size": size, **extra}), content_type="application/json")

	def chunk(self, info, offset, data):
		return self.client.generic("POST", f"{info['chunk_url']}?offset={offset}", data, content_type="application/octet-stream")

	def test_only_admin_can_upload(self):
		self.assertEqual(self.create(10).status_code, 403)
		self.client.force_login(self.member)
		self.assertEqual(self.create(10).status_code, 403)
		self.assertEqual(self.client.get(reverse("tools:share")).status_code, 404)

	def test_chunked_upload_then_anyone_downloads(self):
		import hashlib
		import os
		data = os.urandom(50_000)
		self.client.force_login(self.admin)
		info = self.create(len(data)).json()
		self.assertEqual(self.chunk(info, 0, data[:30_000]).json()["received"], 30_000)
		wrong = self.chunk(info, 0, data[30_000:])  # 잘못된 offset → 현재 위치 알려줌
		self.assertEqual(wrong.status_code, 409)
		self.assertEqual(wrong.json()["received"], 30_000)
		self.chunk(info, 30_000, data[30_000:])
		done = self.client.post(info["complete_url"]).json()
		self.assertEqual(done["sha256"], hashlib.sha256(data).hexdigest())

		self.client.logout()  # 링크만 있으면 누구나
		page = self.client.get(reverse("tools:share_download_page", args=[info["token"]]))
		self.assertContains(page, "data.bin")
		resp = self.client.get(reverse("tools:share_download", args=[info["token"]]))
		self.assertEqual(b"".join(resp.streaming_content), data)

	def test_incomplete_upload_is_not_downloadable_and_complete_checks_size(self):
		self.client.force_login(self.admin)
		info = self.create(100).json()
		self.chunk(info, 0, b"x" * 40)
		self.assertEqual(self.client.post(info["complete_url"]).status_code, 409)
		self.assertEqual(self.client.get(reverse("tools:share_download_page", args=[info["token"]])).status_code, 404)

	def test_expired_links_are_deleted(self):
		import os
		from datetime import timedelta
		from django.utils import timezone
		from tools.models import SharedFile
		self.client.force_login(self.admin)
		info = self.create(5).json()
		self.chunk(info, 0, b"hello")
		self.client.post(info["complete_url"])
		item = SharedFile.objects.get(token=info["token"])
		path = item.file.path
		SharedFile.objects.filter(pk=item.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
		self.assertEqual(self.client.get(reverse("tools:share_download", args=[info["token"]])).status_code, 404)
		self.assertFalse(SharedFile.objects.exists())
		self.assertFalse(os.path.exists(path))

	def test_size_limits(self):
		from unittest import mock
		self.client.force_login(self.admin)
		self.assertEqual(self.create(0).status_code, 400)
		with mock.patch("tools.share_views.MAX_FILE_BYTES", 10):
			self.assertEqual(self.create(11).status_code, 400)
		with mock.patch("tools.share_views.MAX_TOTAL_BYTES", 15):
			self.assertEqual(self.create(10).status_code, 201)
			self.assertEqual(self.create(10).status_code, 507)

	def test_other_user_cannot_append_chunks(self):
		self.client.force_login(self.admin)
		info = self.create(5).json()
		from django.contrib.auth import get_user_model
		other = get_user_model().objects.create_superuser("admin2", "a2@example.com", "pw-for-tests-only")
		self.client.force_login(other)
		self.assertEqual(self.chunk(info, 0, b"hello").status_code, 403)


class KeygenPageTests(TestCase):
	def test_keygen_page_is_public_and_client_side_only(self):
		resp = self.client.get(reverse("tools:keygen"))
		self.assertEqual(resp.status_code, 200)
		self.assertContains(resp, "crypto.getRandomValues")
		self.assertContains(resp, "서버로 전송되지 않아요")
		self.assertNotContains(resp, "fetch(")  # 키를 어디에도 보내지 않음
