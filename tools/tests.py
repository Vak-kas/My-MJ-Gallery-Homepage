from django.test import TestCase
from django.urls import reverse

from .registry import TOOLS


class ToolPagesTests(TestCase):
	def test_hub_lists_every_registered_tool(self):
		resp = self.client.get(reverse("tools:index"))
		self.assertEqual(resp.status_code, 200)
		for tool in TOOLS:
			if tool.get("access") == "admin":
				self.assertNotContains(resp, tool["title"])
				continue
			self.assertContains(resp, tool["title"])
			self.assertContains(resp, reverse(tool["url_name"]))

	def test_tool_pages_match_access(self):
		# public 은 비로그인으로 열리고, member 는 로그인 화면으로 보냄
		for tool in TOOLS:
			status = self.client.get(reverse(tool["url_name"])).status_code
			if tool["access"] == "public":
				self.assertEqual(status, 200, tool["slug"])
			elif tool["access"] == "member":
				self.assertEqual(status, 302, tool["slug"])

	def test_nav_has_tool_link(self):
		resp = self.client.get(reverse("tools:index"))
		self.assertContains(resp, f'href="{reverse("tools:index")}"')

	def test_home_quick_nav_has_tool_link(self):
		resp = self.client.get(reverse("main:home"))
		self.assertContains(resp, f'href="{reverse("tools:index")}"')


class SpeedtestApiTests(TestCase):
	def setUp(self):
		from django.contrib.auth import get_user_model
		from django.core.cache import cache
		cache.clear()
		User = get_user_model()
		self.member = User.objects.create_user("member", "m@example.com", "pw-for-tests-only")
		self.other = User.objects.create_user("other", "o@example.com", "pw-for-tests-only")
		self.client.force_login(self.member)

	def test_requires_login(self):
		self.client.logout()
		self.assertEqual(self.client.get(reverse("tools:speedtest")).status_code, 302)
		for name in ("tools:speedtest_ping", "tools:speedtest_download"):
			self.assertEqual(self.client.get(reverse(name)).status_code, 401)
		resp = self.client.post(reverse("tools:speedtest_upload"), data=b"x", content_type="application/octet-stream")
		self.assertEqual(resp.status_code, 401)

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
		client.force_login(self.member)
		resp = client.post(reverse("tools:speedtest_upload"), data=b"x" * 12345, content_type="application/octet-stream")
		self.assertEqual(resp.status_code, 200)
		self.assertEqual(resp.json()["received"], 12345)

	def test_upload_rejects_oversized_and_empty(self):
		url = reverse("tools:speedtest_upload")
		self.assertEqual(self.client.post(url, data=b"", content_type="application/octet-stream").status_code, 400)
		self.assertEqual(self.client.generic("POST", url, b"x", CONTENT_LENGTH=str(26 * 1024 * 1024)).status_code, 413)

	def test_quota_per_user(self):
		url = reverse("tools:speedtest_download")
		size = 25 * 1024 * 1024
		# 다운로드 한도 1GB / 10분 → 25MB 요청 40번까지 허용
		statuses = [self.client.get(url, {"bytes": size}).status_code for _ in range(41)]
		self.assertEqual(statuses[:40], [200] * 40)
		self.assertEqual(statuses[40], 429)
		blocked = self.client.get(url, {"bytes": size})
		self.assertIn("분 뒤", blocked.json()["error"])
		self.assertGreater(int(blocked["Retry-After"]), 0)
		# 다른 회원은 같은 IP 여도 영향 없음
		self.client.force_login(self.other)
		self.assertEqual(self.client.get(url, {"bytes": size}).status_code, 200)

	def test_quota_window_is_fixed_from_first_request(self):
		from unittest import mock
		url = reverse("tools:speedtest_download")
		size = 25 * 1024 * 1024
		with mock.patch("tools.speedtest.time.time", return_value=1000.0):
			for _ in range(40):
				self.client.get(url, {"bytes": size})
		# 첫 요청 9분 59초 뒤: 아직 막힘
		with mock.patch("tools.speedtest.time.time", return_value=1000.0 + 599):
			self.assertEqual(self.client.get(url, {"bytes": size}).status_code, 429)
		# 첫 요청 10분 뒤: 막힌 동안 요청을 계속 보냈어도 풀림
		with mock.patch("tools.speedtest.time.time", return_value=1000.0 + 600):
			self.assertEqual(self.client.get(url, {"bytes": size}).status_code, 200)

	def test_daily_quota(self):
		from unittest import mock
		url = reverse("tools:speedtest_download")
		size = 25 * 1024 * 1024
		t = 1000.0
		ok = 0
		# 10분마다 1GB 씩 → 하루 3GB(25MB × 122번) 를 넘으면 다음 날까지 막힘
		for _ in range(4):
			with mock.patch("tools.speedtest.time.time", return_value=t):
				for _ in range(40):
					ok += self.client.get(url, {"bytes": size}).status_code == 200
			t += 601
		self.assertEqual(ok, 122)  # 3GB // 25MB
		with mock.patch("tools.speedtest.time.time", return_value=1000.0 + 86400):
			self.assertEqual(self.client.get(url, {"bytes": size}).status_code, 200)

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

	def setUp_cache(self):
		from django.core.cache import cache
		cache.clear()

	def test_anonymous_is_sent_to_login(self):
		resp = self.client.get(reverse("tools:stream"))
		self.assertEqual(resp.status_code, 302)
		self.assertIn(reverse("accounts:login"), resp["Location"])
		self.assertEqual(self.client.post(reverse("tools:stream"), {"kind": "file"}).status_code, 302)

	def test_hub_sections(self):
		from unittest import mock
		from tools import registry
		resp = self.client.get(reverse("tools:index"))
		titles = [s["title"] for s in resp.context["sections"]]
		self.assertEqual(titles, [title for _, _, title, _ in registry.CATEGORIES])  # 분류 순서대로
		for section in resp.context["sections"]:
			self.assertTrue(all(t["category"] == section["key"] for t in section["tools"]))
		self.assertEqual(resp.context["tool_count"], len(registry.TOOLS))
		self.assertContains(resp, "🔒 회원")
		self.assertContains(resp, "로그인하고 쓰기")
		self.assertNotContains(resp, "관리자 전용")  # 관리자 도구가 없으면 칸 자체가 없음
		admin_tool = {"slug": "x", "url_name": "tools:index", "icon": "🛠", "title": "관리자 테스트 도구", "description": "", "tags": [], "access": "admin"}
		with mock.patch.object(registry, "TOOLS", registry.TOOLS + [admin_tool]), mock.patch("tools.views.TOOLS", registry.TOOLS + [admin_tool]):
			self.client.force_login(self.member)
			resp = self.client.get(reverse("tools:index"))
			self.assertNotContains(resp, "관리자 테스트 도구")
			self.assertNotContains(resp, "로그인하고 쓰기")
			self.assertNotContains(resp, "로그인 →")
			self.client.force_login(self.admin)
			resp = self.client.get(reverse("tools:index"))
			self.assertContains(resp, "관리자 전용")
			self.assertContains(resp, "관리자 테스트 도구")

	def test_hub_shows_stream_card_to_everyone_with_login_tag(self):
		self.assertContains(self.client.get(reverse("tools:index")), "데이터 전송")
		self.client.force_login(self.member)
		self.assertContains(self.client.get(reverse("tools:index")), "데이터 전송")

	def _member_room(self, room_id="mem1", owner=None):
		owner = owner or self.member
		return {**self.ROOM, "id": room_id, "token": f"{room_id}-admin", "meta": {"owner_id": owner.id, "owner": owner.username}}

	def test_member_creates_room_with_limits_and_owner(self):
		from unittest import mock
		self.setUp_cache()
		self.client.force_login(self.member)
		with mock.patch("tools.relay_client.list_rooms", return_value=[]), \
				mock.patch("tools.relay_client.create_room", return_value=self._member_room()) as create:
			resp = self.client.post(reverse("tools:stream"), {
				"kind": "file", "ttl_minutes": "360", "rate_mb": "64", "total_gb": "200",
			})
		payload = create.call_args.args[0]
		self.assertEqual(payload["meta"]["owner_id"], self.member.id)
		self.assertEqual(payload["ttl"], 60 * 60)
		self.assertEqual(payload["rate_limit"], 8 * 1024 * 1024)
		self.assertEqual(payload["total_limit"], 3 * 1024 ** 3)
		self.assertEqual(resp.status_code, 302)

	def test_member_one_open_room_and_daily_limit(self):
		from unittest import mock
		self.setUp_cache()
		self.client.force_login(self.member)
		with mock.patch("tools.relay_client.list_rooms", return_value=[self._member_room()]), \
				mock.patch("tools.relay_client.create_room") as create:
			self.client.post(reverse("tools:stream"), {"kind": "file"})
		create.assert_not_called()  # 이미 방 1개 열려 있음
		with mock.patch("tools.relay_client.list_rooms", return_value=[]), \
				mock.patch("tools.relay_client.create_room", return_value=self._member_room()) as create:
			for _ in range(4):
				self.client.post(reverse("tools:stream"), {"kind": "file"})
		self.assertEqual(create.call_count, 3)  # 하루 3개

	def test_member_sees_and_closes_only_own_rooms(self):
		from unittest import mock
		self.setUp_cache()
		mine, theirs = self._member_room("mem1"), self._member_room("adm1", owner=self.admin)
		self.client.force_login(self.member)
		with mock.patch("tools.relay_client.list_rooms", return_value=[mine, theirs]):
			resp = self.client.get(reverse("tools:stream"))
		self.assertContains(resp, "mem1-admin")
		self.assertNotContains(resp, "adm1-admin")
		with mock.patch("tools.relay_client.get_room", return_value=theirs), mock.patch("tools.relay_client.close_room") as close:
			self.assertEqual(self.client.post(reverse("tools:stream_close", args=["adm1"])).status_code, 403)
		close.assert_not_called()
		with mock.patch("tools.relay_client.get_room", return_value=mine), mock.patch("tools.relay_client.close_room") as close:
			self.client.post(reverse("tools:stream_close", args=["mem1"]))
		close.assert_called_once_with("mem1")

	def test_admin_has_no_member_limits(self):
		from unittest import mock
		self.setUp_cache()
		self.client.force_login(self.admin)
		with mock.patch("tools.relay_client.list_rooms", return_value=[self._member_room("a", owner=self.admin)] * 3), \
				mock.patch("tools.relay_client.create_room", return_value=self.ROOM) as create:
			for _ in range(5):
				self.client.post(reverse("tools:stream"), {"kind": "file", "total_gb": "100"})
		self.assertEqual(create.call_count, 5)
		self.assertEqual(create.call_args.args[0]["total_limit"], 100 * 1024 ** 3)

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

	def test_receiver_link_works_without_login(self):
		# 받는 쪽은 회원이 아니어도 링크(토큰)만 있으면 방에 들어오고 계속 입장 유지 가능
		from unittest import mock
		self.client.logout()
		with mock.patch("tools.relay_client.get_room", return_value=self.ROOM), mock.patch("tools.relay_client.join_room", return_value=self.ROOM) as join:
			resp = self.client.get(reverse("tools:stream_room", args=["abc123"]), {"token": "recv-token"}, HTTP_X_REAL_IP="198.51.100.20")
			self.assertEqual(resp.status_code, 200)
			beat = self.client.post(f"{reverse('tools:stream_join', args=['abc123'])}?token=recv-token", HTTP_X_REAL_IP="198.51.100.20")
			self.assertEqual(beat.json()["role"], "receiver")
		self.assertEqual(join.call_count, 2)
		# 방 만들기 화면은 여전히 로그인 필요
		self.assertEqual(self.client.get(reverse("tools:stream")).status_code, 302)

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

	def test_member_cannot_close_others_room_but_admin_can(self):
		from unittest import mock
		with mock.patch("tools.relay_client.get_room", return_value=self.ROOM), mock.patch("tools.relay_client.close_room") as close:
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


class FileRoomPageTests(TestCase):
	ROOM = {**StreamViewTests.ROOM, "kind": "file", "meta": {"label": "파일 방"}, "out_socket": "PUSH"}

	def get(self, token, user=None):
		from unittest import mock
		if user:
			self.client.force_login(user)
		with mock.patch("tools.relay_client.get_room", return_value=self.ROOM), mock.patch("tools.relay_client.join_room", return_value=self.ROOM):
			return self.client.get(reverse("tools:stream_room", args=["abc123"]), {"token": token}).content.decode()

	def test_admin_page_is_sender_only(self):
		from django.contrib.auth import get_user_model
		admin = get_user_model().objects.create_superuser("admin", "admin@example.com", "pw-for-tests-only")
		html = self.get("secret-token", admin)
		self.assertIn('id="fx-out"', html)  # 파일 보내기
		self.assertNotIn('id="fx-in"', html)  # 관리자 화면에서 자기 파일을 받지 않음
		self.assertIn("?token=recv-token", html)  # 받는 쪽 링크는 나눠 줄 수 있음
		self.assertNotIn("data-join=", html)  # 파일 방엔 IP 등록 버튼 없음

	def test_receiver_link_only_receives(self):
		html = self.get("recv-token")
		self.assertIn('id="fx-in"', html)
		self.assertNotIn('id="fx-out"', html)

	def test_sender_link_only_sends(self):
		html = self.get("send-token")
		self.assertIn('id="fx-out"', html)
		self.assertNotIn('id="fx-in"', html)

	def test_file_room_has_no_gnu_radio_blocks(self):
		html = self.get("send-token")
		self.assertNotIn("GNU Radio 블록", html)
		self.assertIn("mj_stream.py send", html)


class MyIpTests(TestCase):
	def setUp(self):
		from django.core.cache import cache
		cache.clear()

	def test_page_shows_client_ip(self):
		from unittest import mock
		with mock.patch("tools.myip._reverse_dns", return_value="host.example.net"):
			resp = self.client.get(reverse("tools:myip"), HTTP_X_REAL_IP="203.0.113.9", HTTP_USER_AGENT="TestAgent/1.0")
		self.assertContains(resp, "203.0.113.9")
		self.assertContains(resp, "IPv4")
		self.assertContains(resp, "TestAgent/1.0")

	def test_ipv6_and_private(self):
		resp = self.client.get(reverse("tools:myip"), HTTP_X_REAL_IP="2001:db8::1")
		self.assertContains(resp, "IPv6")
		resp = self.client.get(reverse("tools:myip"), HTTP_X_REAL_IP="192.168.0.5")
		self.assertContains(resp, "사설·로컬 주소")
		self.assertEqual(self.client.get(reverse("tools:myip_lookup"), HTTP_X_REAL_IP="192.168.0.5").status_code, 400)

	def test_lookup_summarizes_rdap_and_caches(self):
		import io
		import json
		from unittest import mock
		rdap = {
			"name": "KORNET", "country": "KR", "startAddress": "1.96.0.0", "endAddress": "1.111.255.255",
			"entities": [{"roles": ["registrant"], "vcardArray": ["vcard", [["version", {}, "text", "4.0"], ["fn", {}, "text", "Korea Telecom"]]]}],
		}
		fake = mock.MagicMock()
		fake.__enter__.return_value = io.BytesIO(json.dumps(rdap).encode())
		with mock.patch("tools.myip.urllib.request.urlopen", return_value=fake) as urlopen:
			data = self.client.get(reverse("tools:myip_lookup"), HTTP_X_REAL_IP="1.97.1.1").json()
			self.client.get(reverse("tools:myip_lookup"), HTTP_X_REAL_IP="1.97.1.1")
		self.assertEqual(data["network"], "KORNET")
		self.assertEqual(data["org"], ["Korea Telecom"])
		self.assertEqual(data["country"], "KR")
		self.assertEqual(urlopen.call_count, 1)  # 두 번째는 캐시
		self.assertIn("1.97.1.1", urlopen.call_args.args[0].full_url)

	def test_lookup_rate_limited(self):
		from unittest import mock
		with mock.patch("tools.myip.urllib.request.urlopen", side_effect=OSError):
			codes = [self.client.get(reverse("tools:myip_lookup"), HTTP_X_REAL_IP="8.8.4.4").status_code for _ in range(11)]
		self.assertEqual(codes[-1], 429)

	def test_encode_page_is_public(self):
		self.assertContains(self.client.get(reverse("tools:encode")), "MD5")


class NetCheckTests(TestCase):
	def setUp(self):
		from django.contrib.auth import get_user_model
		from django.core.cache import cache
		cache.clear()
		self.member = get_user_model().objects.create_user("member", "m@example.com", "pw-for-tests-only")
		self.client.force_login(self.member)

	def run_check(self, **data):
		import json
		return self.client.post(reverse("tools:netcheck_run"), json.dumps(data), content_type="application/json")

	def test_requires_login(self):
		self.client.logout()
		self.assertEqual(self.client.get(reverse("tools:netcheck")).status_code, 302)
		self.assertEqual(self.run_check(type="ping", host="example.com").status_code, 401)

	def test_blocks_internal_targets(self):
		for host in ("127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.1.1", "[::1]", "localhost"):
			resp = self.run_check(type="port", host=host, ports="22")
			self.assertEqual(resp.status_code, 400, host)

	def test_rejects_bad_host_and_ports(self):
		self.assertIn("올바르지", self.run_check(type="ping", host="bad host;rm -rf").json()["error"])
		self.assertIn("10개", self.run_check(type="port", host="8.8.8.8", ports="1-20").json()["error"])
		self.assertEqual(self.run_check(type="nope", host="8.8.8.8").status_code, 400)

	def test_port_check_states(self):
		from unittest import mock
		from tools import netcheck
		def fake_probe(ip, port, timeout=2.5):
			return {"port": port, "state": {22: "open", 80: "closed"}.get(port, "filtered"), **({"ms": 12.3} if port == 22 else {})}
		with mock.patch.object(netcheck, "_resolve", return_value=["93.184.216.34"]), mock.patch.object(netcheck, "_probe", side_effect=fake_probe):
			data = self.run_check(type="port", host="https://example.com/path", ports="22, 80 443").json()
		self.assertEqual(data["host"], "example.com")
		self.assertEqual(data["target"], "93.184.216.34")
		self.assertEqual([(p["port"], p["state"], p["service"]) for p in data["ports"]],
			[(22, "open", "SSH"), (80, "closed", "HTTP"), (443, "filtered", "HTTPS")])

	def test_ping_parses_summary_and_passes_ip_only(self):
		from unittest import mock
		from tools import netcheck
		out = "4 packets transmitted, 4 received, 0% packet loss\nrtt min/avg/max/mdev = 1.1/2.2/3.3/0.4 ms"
		with mock.patch.object(netcheck, "_resolve", return_value=["8.8.8.8"]), mock.patch.object(netcheck, "_run", return_value=out) as run:
			data = self.run_check(type="ping", host="dns.google").json()
		self.assertEqual(data["summary"], {"sent": 4, "received": 4, "min": 1.1, "avg": 2.2, "max": 3.3})
		self.assertEqual(run.call_args.args[0][-1], "8.8.8.8")  # 명령에는 검증된 IP 만 들어감

	def test_rate_limit(self):
		from unittest import mock
		from tools import netcheck
		with mock.patch.object(netcheck, "check_dns", return_value={}):
			codes = [self.run_check(type="dns", host="example.com").status_code for _ in range(21)]
		self.assertEqual(codes[:20], [200] * 20)
		self.assertEqual(codes[20], 429)


class ShortLinkTests(TestCase):
	def setUp(self):
		from django.contrib.auth import get_user_model
		User = get_user_model()
		self.member = User.objects.create_user("member", "m@example.com", "pw-for-tests-only")
		self.other = User.objects.create_user("other", "o@example.com", "pw-for-tests-only")
		self.client.force_login(self.member)

	def test_requires_login_to_create(self):
		self.client.logout()
		self.assertEqual(self.client.get(reverse("tools:shortlink")).status_code, 302)

	def test_create_and_redirect_counts_clicks(self):
		from tools.models import ShortLink
		self.client.post(reverse("tools:shortlink"), {"url": "example.com/very/long?x=1"})
		link = ShortLink.objects.get()
		self.assertEqual(link.target_url, "https://example.com/very/long?x=1")
		self.client.logout()  # 여는 건 누구나
		resp = self.client.get(f"/s/{link.code}")
		self.assertRedirects(resp, "https://example.com/very/long?x=1", fetch_redirect_response=False)
		link.refresh_from_db()
		self.assertEqual(link.click_count, 1)

	def test_rejects_bad_scheme_and_loops(self):
		from tools.models import ShortLink
		for url in ("javascript:alert(1)", "ftp://example.com/x", "http://testserver/s/abc"):
			self.client.post(reverse("tools:shortlink"), {"url": url})
		self.assertFalse(ShortLink.objects.exists())

	def test_expired_and_missing_show_gone_page(self):
		from datetime import timedelta
		from django.utils import timezone
		from tools.models import ShortLink
		ShortLink.objects.create(code="old123", target_url="https://example.com", owner=self.member, expires_at=timezone.now() - timedelta(seconds=1))
		self.assertContains(self.client.get("/s/old123"), "만료된", status_code=404)
		self.assertEqual(self.client.get("/s/nothere").status_code, 404)

	def test_only_owner_deletes(self):
		from tools.models import ShortLink
		link = ShortLink.objects.create(code="mine01", target_url="https://example.com", owner=self.member)
		self.client.force_login(self.other)
		self.assertEqual(self.client.post(reverse("tools:shortlink_delete", args=["mine01"])).status_code, 404)
		self.client.force_login(self.member)
		self.client.post(reverse("tools:shortlink_delete", args=["mine01"]))
		self.assertFalse(ShortLink.objects.filter(pk=link.pk).exists())


class SecretNoteTests(TestCase):
	def setUp(self):
		from django.contrib.auth import get_user_model
		self.member = get_user_model().objects.create_user("member", "m@example.com", "pw-for-tests-only")
		self.client.force_login(self.member)

	def create(self, **extra):
		import json
		return self.client.post(reverse("tools:secret_create"), json.dumps({"ciphertext": "AAAAenc", "label": "와이파이", "ttl": "1", **extra}), content_type="application/json")

	def test_create_requires_login(self):
		self.client.logout()
		self.assertEqual(self.create().status_code, 302)

	def test_reveal_once(self):
		from tools.models import SecretNote
		url = self.create().json()["url"]
		note = SecretNote.objects.get()
		self.assertIn(note.note_id, url)
		self.client.logout()  # 받는 사람은 로그인 없이
		view = self.client.get(reverse("tools:secret_view", args=[note.note_id]))
		self.assertContains(view, "메모 열기")
		note.refresh_from_db()
		self.assertEqual(note.ciphertext, "AAAAenc")  # 화면만 열어서는(링크 미리보기 등) 안 지워짐
		first = self.client.post(reverse("tools:secret_reveal", args=[note.note_id]))
		self.assertEqual(first.json(), {"ciphertext": "AAAAenc"})
		second = self.client.post(reverse("tools:secret_reveal", args=[note.note_id]))
		self.assertEqual(second.status_code, 410)
		note.refresh_from_db()
		self.assertEqual(note.ciphertext, "")
		self.assertIsNotNone(note.opened_at)
		self.assertContains(self.client.get(reverse("tools:secret_view", args=[note.note_id])), "이미 열어 본")

	def test_expired_cannot_reveal(self):
		from datetime import timedelta
		from django.utils import timezone
		from tools.models import SecretNote
		self.create()
		note = SecretNote.objects.get()
		SecretNote.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
		self.assertEqual(self.client.post(reverse("tools:secret_reveal", args=[note.note_id])).status_code, 410)

	def test_size_limit(self):
		self.assertEqual(self.create(ciphertext="A" * 20001).status_code, 400)
		self.assertEqual(self.create(ciphertext="").status_code, 400)


class LiveViewTests(TestCase):
	ROOM = {"id": "live01", "token": "host-tok", "viewer_token": "view-tok", "title": "테스트", "owner_id": None, "owner": "seo",
			"max_viewers": 5, "chat": True, "expires_in": 3600, "host_online": False, "viewers": 0}

	def setUp(self):
		from django.contrib.auth import get_user_model
		from django.core.cache import cache
		cache.clear()
		User = get_user_model()
		self.admin = User.objects.create_superuser("admin", "a@example.com", "pw-for-tests-only")
		self.member = User.objects.create_user("member", "m@example.com", "pw-for-tests-only")

	def room(self, owner=None):
		return {**self.ROOM, "owner_id": (owner or self.member).id}

	def test_list_requires_login(self):
		self.assertEqual(self.client.get(reverse("tools:live")).status_code, 302)

	def test_member_create_applies_limits(self):
		from unittest import mock
		self.client.force_login(self.member)
		with mock.patch("tools.relay_client.list_live", return_value=[]), \
				mock.patch("tools.relay_client.create_live", return_value=self.room()) as create:
			resp = self.client.post(reverse("tools:live"), {"title": "발표", "ttl_minutes": "999", "max_viewers": "50", "chat": "on"})
		payload = create.call_args.args[0]
		self.assertEqual((payload["ttl"], payload["max_viewers"], payload["chat"], payload["owner_id"]), (120 * 60, 5, True, self.member.id))
		self.assertEqual(resp["Location"], f"{reverse('tools:live_room', args=['live01'])}?token=host-tok")

	def test_member_one_room_and_daily_limit(self):
		from unittest import mock
		self.client.force_login(self.member)
		with mock.patch("tools.relay_client.list_live", return_value=[self.room()]), mock.patch("tools.relay_client.create_live") as create:
			self.client.post(reverse("tools:live"), {"title": "x"})
		create.assert_not_called()
		with mock.patch("tools.relay_client.list_live", return_value=[]), \
				mock.patch("tools.relay_client.create_live", return_value=self.room()) as create:
			for _ in range(4):
				self.client.post(reverse("tools:live"), {"title": "x"})
		self.assertEqual(create.call_count, 3)

	def test_viewer_link_works_without_login_and_hides_host_token(self):
		from unittest import mock
		with mock.patch("tools.relay_client.get_live", return_value=self.room()):
			resp = self.client.get(reverse("tools:live_room", args=["live01"]), {"token": "view-tok"})
			self.assertEqual(resp.status_code, 200)
			self.assertEqual(resp.context["role"], "viewer")
			self.assertNotContains(resp, "host-tok")
			self.assertContains(resp, "시청하기")
			bad = self.client.get(reverse("tools:live_room", args=["live01"]), {"token": "nope"})
		self.assertEqual(bad.status_code, 404)

	def test_host_page_shows_viewer_link(self):
		from unittest import mock
		self.client.force_login(self.member)
		with mock.patch("tools.relay_client.get_live", return_value=self.room()):
			resp = self.client.get(reverse("tools:live_room", args=["live01"]), {"token": "host-tok"})
		self.assertEqual(resp.context["role"], "host")
		self.assertIn("token=view-tok", resp.context["viewer_link"])

	def test_turn_credentials(self):
		import base64, hashlib, hmac
		from django.test import override_settings
		from tools.live_views import ice_servers
		with override_settings(TURN_SECRET="s3cret", TURN_HOST="turn.example", TURN_PORT=3478):
			servers = ice_servers("live01", 3600)
		turn = servers[-1]
		self.assertIn("turn:turn.example:3478?transport=udp", turn["urls"])
		expected = base64.b64encode(hmac.new(b"s3cret", turn["username"].encode(), hashlib.sha1).digest()).decode()
		self.assertEqual(turn["credential"], expected)
		self.assertTrue(turn["username"].endswith(":live01"))
		with override_settings(TURN_SECRET=""):
			self.assertEqual(len(ice_servers("live01", 60)), 1)  # STUN 만

	def test_only_owner_or_admin_closes(self):
		from unittest import mock
		other = self.room(owner=self.admin)
		self.client.force_login(self.member)
		with mock.patch("tools.relay_client.get_live", return_value=other), mock.patch("tools.relay_client.close_live") as close:
			self.assertEqual(self.client.post(reverse("tools:live_close", args=["live01"])).status_code, 404)
		close.assert_not_called()
		self.client.force_login(self.admin)
		with mock.patch("tools.relay_client.get_live", return_value=self.room()), mock.patch("tools.relay_client.close_live") as close:
			self.client.post(reverse("tools:live_close", args=["live01"]))
		close.assert_called_once_with("live01")


class QrAiTests(TestCase):
	def setUp(self):
		from django.contrib.auth import get_user_model
		from django.core.cache import cache
		cache.clear()
		self.member = get_user_model().objects.create_user("member", "m@example.com", "pw-for-tests-only")

	def post(self, prompt="피카츄 느낌", **extra):
		import json
		return self.client.post(reverse("tools:qrcode_ai"), json.dumps({"prompt": prompt, **extra}), content_type="application/json")

	def test_requires_login_and_key(self):
		from django.test import override_settings
		self.assertEqual(self.post().status_code, 401)
		self.client.force_login(self.member)
		with override_settings(ANTHROPIC_API_KEY=""):
			self.assertEqual(self.post().status_code, 503)

	def test_sanitizes_and_fixes_contrast(self):
		from unittest import mock
		from django.test import override_settings
		raw = {"name": "피카츄 테마입니다아아아", "reason": "노랑", "shape": "heart", "fg": "#ffee88", "grad": "radial", "fg2": "not-a-color",
			"eye": "triangle", "eyeball": "circle", "eyec": "#ffd400", "eyeballc": "#e53935", "bg": "#fff8d0", "frame": "ticket", "caption": "", "framec": "#333333"}
		self.client.force_login(self.member)
		with override_settings(ANTHROPIC_API_KEY="k"), mock.patch("tools.qr_ai._ask_claude", return_value=raw) as ask:
			data = self.post(has_logo=True).json()
		self.assertEqual(ask.call_args.args[1:], ("피카츄 느낌", True))
		from tools.qr_ai import _contrast
		self.assertEqual(data["shape"], "heart")
		self.assertEqual(data["eye"], "square")  # 허용되지 않은 값 → 기본값
		self.assertEqual(data["caption"], "SCAN ME")
		self.assertLessEqual(len(data["name"]), 12)
		for key in ("fg", "fg2", "eyec", "eyeballc", "framec"):
			self.assertGreaterEqual(_contrast(data[key], data["bg"]), 4.5, key)

	def test_dark_background_forced_light(self):
		from tools.qr_ai import sanitize
		out = sanitize({"bg": "#111111", "fg": "#eeeeee"})
		self.assertEqual(out["bg"], "#ffffff")

	def test_daily_limit(self):
		from unittest import mock
		from django.test import override_settings
		self.client.force_login(self.member)
		fake = {"content": [{"type": "tool_use", "input": {}}], "usage": {"input_tokens": 10, "output_tokens": 5}}
		with override_settings(ANTHROPIC_API_KEY="k"), mock.patch("tools.ai._post", return_value=fake):
			codes = [self.post().status_code for _ in range(21)]
		self.assertEqual(codes[:20], [200] * 20)
		self.assertEqual(codes[20], 429)

	def test_request_shape(self):
		import io
		import json
		from unittest import mock
		from django.test import override_settings
		from tools import qr_ai
		fake = mock.MagicMock()
		fake.__enter__.return_value = io.BytesIO(json.dumps({"content": [{"type": "tool_use", "input": {"shape": "star"}}]}).encode())
		with override_settings(ANTHROPIC_API_KEY="secret-k", ANTHROPIC_MODEL="claude-haiku-5-5"), \
				mock.patch("tools.ai.urllib.request.urlopen", return_value=fake) as urlopen:
			result = qr_ai._ask_claude(self.member, "사이버펑크", False)
		req = urlopen.call_args.args[0]
		body = json.loads(req.data)
		self.assertEqual(result, {"shape": "star"})
		self.assertEqual(req.get_header("X-api-key"), "secret-k")
		self.assertEqual(body["tool_choice"], {"type": "tool", "name": "apply_qr_style"})
		self.assertEqual(body["model"], "claude-haiku-5-5")


class ToolRegistryTests(TestCase):
	def test_every_tool_has_known_category_and_unique_slug(self):
		from .registry import CATEGORIES

		keys = {key for key, *_ in CATEGORIES}
		for tool in TOOLS:
			self.assertIn(tool.get("category"), keys, tool["slug"])
			self.assertIn(tool.get("access"), {"public", "member", "admin"}, tool["slug"])
		slugs = [t["slug"] for t in TOOLS]
		self.assertEqual(len(slugs), len(set(slugs)))


class CiteTests(TestCase):
	CROSSREF = {"message": {
		"DOI": "10.1109/CVPR.2016.90", "type": "proceedings-article", "title": ["Deep Residual Learning for Image Recognition"],
		"author": [{"given": "Kaiming", "family": "He"}, {"given": "Xiangyu", "family": "Zhang"}],
		"issued": {"date-parts": [[2016, 6]]}, "container-title": ["2016 IEEE Conference on Computer Vision and Pattern Recognition (CVPR)"],
		"page": "770-778", "publisher": "IEEE",
	}}
	ARXIV = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
	<entry><id>http://arxiv.org/abs/1706.03762v7</id><published>2017-06-12T17:57:34Z</published><title>Attention Is All
	You Need</title><author><name>Ashish Vaswani</name></author><author><name>Noam Shazeer</name></author>
	<arxiv:primary_category term="cs.CL"/></entry></feed>"""
	GPP = (b"<html><body><span>Specification #: 38.321</span> Title: <b>NR; Medium Access Control (MAC) protocol specification</b> Status: Under change control "
		b"Type: Technical specification (TS) <table><tr><td>RAN#113</td><td>19.4.0</td><td>2026-09-25</td></tr>"
		b"<tr><td>18.10.0</td><td>2026-06-29</td></tr><tr><td>18.9.0</td><td>2026-03-20</td></tr><tr><td>17.0.0</td><td>2022-04-14</td></tr></table></body></html>")

	def setUp(self):
		from django.core.cache import cache
		cache.clear()

	def fake(self, url, accept="application/json"):
		import json
		if "crossref.org/works/" in url:
			return json.dumps(self.CROSSREF).encode()
		if "crossref.org/works?" in url:
			return json.dumps({"message": {"items": [self.CROSSREF["message"]]}}).encode()
		if "arxiv.org" in url:
			return self.ARXIV
		if "3gpp.org" in url:
			return self.GPP
		raise AssertionError(url)

	def get(self, q):
		from unittest import mock
		with mock.patch("tools.cite._get", side_effect=self.fake) as m:
			res = self.client.get(reverse("tools:cite_lookup"), {"q": q})
		return res, m

	def test_classify(self):
		from . import cite
		self.assertEqual(cite.classify("https://doi.org/10.1109/CVPR.2016.90."), ("doi", "10.1109/cvpr.2016.90"))
		self.assertEqual(cite.classify("https://arxiv.org/abs/1706.03762v7"), ("arxiv", "1706.03762"))
		self.assertEqual(cite.classify("TR 38.901 v17.0.0"), ("3gpp", "38.901@17.0.0"))
		self.assertEqual(cite.classify("38321"), ("3gpp", "38.321"))
		self.assertEqual(cite.classify("Attention is all you need")[0], "search")

	def test_doi_and_cache(self):
		res, m = self.get("10.1109/CVPR.2016.90")
		item = res.json()["items"][0]
		self.assertEqual((item["type"], item["year"], item["pages"], item["doi"]), ("inproceedings", 2016, "770-778", "10.1109/CVPR.2016.90"))
		self.assertEqual(item["authors"][0], {"family": "He", "given": "Kaiming"})
		res, m = self.get("doi:10.1109/cvpr.2016.90")
		self.assertFalse(m.called)  # 두 번째는 캐시

	def test_arxiv_and_search(self):
		item = self.get("arXiv:1706.03762")[0].json()["items"][0]
		self.assertEqual((item["title"], item["arxiv"], item["primary_class"]), ("Attention Is All You Need", "1706.03762", "cs.CL"))
		items = self.get("Attention is all you need")[0].json()["items"]
		self.assertEqual(items[0]["source"], "arxiv")  # 제목이 같은 게 먼저

	def test_3gpp_latest_and_version(self):
		item = self.get("TS 38.321")[0].json()["items"][0]
		self.assertEqual((item["number"], item["version"], item["year"], item["month"], item["report_type"]), ("TS 38.321", "19.4.0", 2026, 9, "Technical Specification (TS)"))
		self.assertEqual([r["version"] for r in item["releases"]], ["19.4.0", "18.10.0", "17.0.0"])  # 릴리스마다 최신 하나
		item = self.get("38.321 v18.9.0")[0].json()["items"][0]
		self.assertEqual((item["version"], item["release"]), ("18.9.0", 18))
		self.assertEqual(self.get("38.321 v9.9.9")[0].status_code, 404)

	def test_rate_limit_counts_only_upstream_calls(self):
		from unittest import mock
		with mock.patch.dict("tools.cite.LIMITS", {"anon": 2}):
			self.assertEqual(self.get("10.1109/a")[0].status_code, 200)
			self.assertEqual(self.get("10.1109/a")[0].status_code, 200)  # 캐시라 안 셈
			self.assertEqual(self.get("10.1109/b")[0].status_code, 200)
			self.assertEqual(self.get("10.1109/c")[0].status_code, 429)

	def test_page(self):
		self.assertContains(self.client.get(reverse("tools:cite")), "논문 인용 만들기")


class PapersTests(TestCase):
	WORK = {
		"id": "https://openalex.org/W123", "doi": "https://doi.org/10.1109/JIOT.2023.1", "ids": {}, "title": "Anti-Jamming for <i>Satellite</i> IoT",
		"publication_year": 2023, "publication_date": "2023-06-01", "type": "article", "cited_by_count": 20, "referenced_works_count": 40,
		"authorships": [{"author": {"display_name": "Gil Dong Hong"}}, {"author": {"display_name": "Jane Doe"}}],
		"primary_location": {"source": {"id": "https://openalex.org/S2480266640", "display_name": "IEEE Internet of Things Journal", "type": "journal", "host_organization_name": "IEEE"}},
		"locations": [{"landing_page_url": "https://arxiv.org/abs/2301.01234v2", "pdf_url": ""}],
		"open_access": {"is_oa": True}, "best_oa_location": {"pdf_url": "https://arxiv.org/pdf/2301.01234"},
		"biblio": {"volume": "10", "issue": "5", "first_page": "100", "last_page": "110"},
		"abstract_inverted_index": {"Jamming": [0], "is": [1], "bad": [2]},
	}

	def setUp(self):
		from django.core.cache import cache
		cache.clear()

	def test_build_query(self):
		from . import papers
		q, groups = papers.build_query("NTN jamming")
		self.assertIn('"non-terrestrial"', q)
		self.assertIn("AND (jamming OR jammer", q)
		self.assertEqual(papers.build_query("physical layer security UAV")[0].split(" AND ")[0], '"physical layer security"')
		self.assertEqual(papers.build_query("위성, 재밍")[0].split(" AND ")[1], "(jamming OR jammer)")  # 한국어 → 영어, 쉼표는 지움
		self.assertEqual(papers.build_query("(LEO OR GEO) AND jamming")[0], "(LEO OR GEO) AND jamming")  # 직접 쓴 건 그대로
		self.assertEqual(papers.build_query("ntn", expand=False)[0], "ntn")

	def test_normalize(self):
		from . import papers
		p = papers.normalize(self.WORK)
		self.assertEqual((p["id"], p["doi"], p["arxiv"], p["title"], p["pages"], p["venue_type"]), ("W123", "10.1109/JIOT.2023.1", "2301.01234", "Anti-Jamming for Satellite IoT", "100-110", "journal"))
		self.assertEqual(p["abstract"], "Jamming is bad")

	def search(self, url, response):
		from unittest import mock
		with mock.patch("tools.papers._openalex", return_value=response) as m:
			res = self.client.get(url)
		return res, m

	def test_search_sort_and_cache(self):
		other = {**self.WORK, "id": "https://openalex.org/W9", "doi": None, "title": "Older", "cited_by_count": 99, "publication_date": "2020-01-01"}
		data = {"meta": {"count": 2}, "results": [self.WORK, other]}
		res, m = self.search("/tools/papers/search/?q=NTN+jamming&sort=cited&venues=iotj,nope", data)
		body = res.json()
		self.assertEqual([i["id"] for i in body["items"]], ["W9", "W123"])
		flt = m.call_args[0][0]["filter"]
		self.assertIn("primary_location.source.id:S2480266640", flt)
		self.assertNotIn("primary_topic.subfield", flt)  # 저널을 고르면 분야 필터는 안 씀
		res, m = self.search("/tools/papers/search/?q=NTN+jamming&sort=recent&venues=iotj", data)
		self.assertFalse(m.called)  # 정렬만 바꾸면 캐시
		self.assertEqual([i["id"] for i in res.json()["items"]], ["W123", "W9"])

	def test_related_and_errors(self):
		res, m = self.search("/tools/papers/search/?rel=refs:W123", {"meta": {"count": 1}, "results": [self.WORK]})
		self.assertEqual(m.call_args[0][0]["filter"], "cited_by:W123")
		self.assertEqual(self.client.get("/tools/papers/search/?rel=refs:bad").status_code, 400)
		self.assertEqual(self.client.get("/tools/papers/search/?q=a").status_code, 400)

	def test_budget_guard(self):
		from django.core.cache import cache
		from . import papers
		cache.set(papers.BUDGET_KEY, 0.001)
		res = self.client.get("/tools/papers/search/?q=NTN+jamming")
		self.assertEqual(res.status_code, 503)

	def test_shelf(self):
		import json
		from django.contrib.auth import get_user_model
		from . import papers
		self.assertEqual(self.client.get("/tools/papers/shelf/").status_code, 302)
		user = get_user_model().objects.create_user("u", "u@example.com", "pw")
		self.client.force_login(user)
		item = papers.normalize(self.WORK)
		post = lambda url, body: self.client.post(url, json.dumps(body), content_type="application/json")
		saved = post("/tools/papers/shelf/save/", {"data": item}).json()["item"]
		post("/tools/papers/shelf/save/", {"data": item})  # 같은 논문은 하나만
		self.assertEqual(len(self.client.get("/tools/papers/shelf/").json()["items"]), 1)
		self.assertEqual(saved["key"], "10.1109/jiot.2023.1")
		upd = post(f"/tools/papers/shelf/{saved['id']}/", {"status": "done", "starred": True, "note": "시스템 모델 참고"}).json()["item"]
		self.assertEqual((upd["status"], upd["starred"], upd["note"]), ("done", True, "시스템 모델 참고"))
		other = get_user_model().objects.create_user("v", "v@example.com", "pw")
		self.client.force_login(other)
		self.assertEqual(post(f"/tools/papers/shelf/{saved['id']}/", {"delete": True}).status_code, 404)  # 남의 것은 못 건드림
		self.client.force_login(user)
		self.assertTrue(post(f"/tools/papers/shelf/{saved['id']}/", {"delete": True}).json()["deleted"])


class PaperSectionsTests(TestCase):
	HTML = """<html><body><article class="ltx_document"><h1 class="ltx_title ltx_title_document">Anti-Jamming in LEO</h1>
	<div class="ltx_abstract"><p class="ltx_p">We study jamming.</p></div>
	<section id="S1" class="ltx_section"><h2 class="ltx_title ltx_title_section"><span class="ltx_tag">I </span>Introduction</h2>
	<div class="ltx_para"><p class="ltx_p">Satellites are everywhere <cite class="ltx_cite">[<a href="#bib.bib1" class="ltx_ref">1</a>, <a href="#bib.bib2" class="ltx_ref">2</a>]</cite>.</p></div>
	<div class="ltx_para"><p class="ltx_p">However, jamming has not been studied in <a href="#x">LEO</a>.<script>alert(1)</script></p></div>
	<div class="ltx_para"><p class="ltx_p">The main contributions are summarized as follows:</p>
	<ul class="ltx_itemize"><li class="ltx_item">1. A new model <math alttext="x^2" display="inline"></math>.</li><li class="ltx_item">2. A new algorithm.</li></ul></div>
	<div class="ltx_para"><p class="ltx_p">The rest of this paper is organized as follows.</p></div></section>
	<section id="S2" class="ltx_section"><h2 class="ltx_title">II System Model</h2>
	<section class="ltx_subsection"><h3 class="ltx_title">II-A Channel</h3><div class="ltx_para"><p class="ltx_p">The channel is</p>
	<table class="ltx_equation ltx_eqn_table"><tr><td><math alttext="h = g\\sqrt{\\beta}" display="block"></math></td><td class="ltx_eqn_eqno">(1)</td></tr></table></div></section></section>
	<section id="S3" class="ltx_section"><h2 class="ltx_title">III Simulation Results</h2><div class="ltx_para"><p class="ltx_p">Results.</p></div></section>
	<section class="ltx_bibliography"><ul><li id="bib.bib1" class="ltx_bibitem"><span class="ltx_tag ltx_tag_bibitem">[1]</span><span class="ltx_bibblock">A. Kim, “LEO networks,” IEEE TWC, 2020.</span></li>
	<li id="bib.bib2" class="ltx_bibitem"><span class="ltx_tag ltx_tag_bibitem">[2]</span><span class="ltx_bibblock">B. Lee, “NTN,” 2021.</span></li></ul></section></article></body></html>"""

	def setUp(self):
		from django.core.cache import cache
		cache.clear()

	def test_arxiv_html(self):
		import json
		from . import paper_sections as ps
		out = ps.from_arxiv_html(self.HTML)
		self.assertEqual(out["title"], "Anti-Jamming in LEO")
		self.assertEqual([s["kind"] for s in out["sections"]], ["abstract", "introduction", "system", "simulation"])
		intro = out["sections"][1]
		self.assertEqual([b.get("role") for b in intro["blocks"] if b["t"] == "p"], ["background", "gap", "this", "organization"])
		self.assertEqual(len(intro["contributions"]), 2)
		self.assertTrue(intro["contributions"][0].startswith("A new model"))
		self.assertIn('data-latex="x^2"', intro["contributions"][0])
		self.assertEqual(intro["cited"], ["bib.bib1", "bib.bib2"])
		self.assertIn("LEO networks", out["refs"]["bib.bib1"]["text"])
		self.assertNotIn("<script", json.dumps(out))  # 원문 HTML 은 그대로 안 넘김
		system = out["sections"][2]["blocks"]
		self.assertEqual([b["t"] for b in system], ["h", "p", "eq"])
		self.assertEqual(system[2]["rows"][0], {"latex": "h = g\\sqrt{\\beta}", "no": "(1)"})

	def test_pdf(self):
		import fitz
		from . import paper_sections as ps
		doc = fitz.open()
		lines = [("Abstract—We study jamming in LEO.", 9, False), ("I. INTRODUCTION", 11, True), ("Satellites matter [1], [2]–[3].", 10, False),
				 ("", 0, False), ("In this paper, our contributions are:", 10, False), ("", 0, False), ("1) A model. 2) An algorithm.", 10, False),
				 ("II. SYSTEM MODEL", 11, True), ("We consider a LEO satellite.", 10, False), ("REFERENCES", 11, True),
				 ("[1] A. Kim, “LEO networks,” 2020.", 9, False), ("[2] B. Lee, “NTN,” 2021.", 9, False), ("[3] C. Park, “Jam,” 2022.", 9, False)]
		page = doc.new_page()
		y = 60
		for text, size, bold in lines:
			if text:
				page.insert_text((60, y), text, fontsize=size, fontname="hebo" if bold else "helv")
			y += 24 if text else 12
		out = ps.from_pdf(doc.tobytes())
		self.assertEqual([s["kind"] for s in out["sections"]], ["abstract", "introduction", "system"])
		intro = out["sections"][1]
		self.assertEqual(intro["cited"], ["ref.1", "ref.2", "ref.3"])  # [2]–[3] 범위도 풀기
		self.assertIn("LEO networks", out["refs"]["ref.1"]["text"])

	def test_view_cache_and_errors(self):
		from unittest import mock
		from . import paper_sections as ps
		with mock.patch("tools.paper_sections._fetch", return_value=self.HTML.encode()) as m:
			self.assertEqual(self.client.get("/tools/papers/sections/?arxiv=2401.09157").json()["arxiv"], "2401.09157")
			self.client.get("/tools/papers/sections/?arxiv=2401.09157")
		self.assertEqual(m.call_count, 1)  # 두 번째는 캐시
		self.assertEqual(self.client.get("/tools/papers/sections/?arxiv=../../etc").status_code, 400)
		with mock.patch("tools.paper_sections.find_arxiv", return_value=""):
			res = self.client.get("/tools/papers/sections/?title=Some+paywalled+IEEE+paper+title")
		self.assertEqual(res.status_code, 404)
		self.assertTrue(res.json()["need_pdf"])
		self.assertEqual(self.client.post("/tools/papers/sections/pdf/").status_code, 302)  # PDF 올리기는 회원만


class PaperAITests(TestCase):
	def setUp(self):
		from django.contrib.auth import get_user_model
		from django.core.cache import cache
		cache.clear()
		self.user = get_user_model().objects.create_user("u", "u@example.com", "pw")

	def post(self, body):
		import json
		return self.client.post("/tools/papers/ai/", json.dumps(body), content_type="application/json")

	def test_summary_trims_and_caches(self):
		from unittest import mock
		from . import paper_ai
		self.assertEqual(self.post({"mode": "summary", "title": "T", "sections": {"abstract": "x"}}).status_code, 401)  # 로그인 필요
		self.client.force_login(self.user)
		long = {"abstract": "a" * 3000, "introduction": "i" * 9000, "system": "s" * 9000, "simulation": "r" * 3000}
		raw = {**{k: f"{label} 값" for k, label in paper_ai.FIELDS}, "keywords": ["LEO jamming", "anti-jamming"]}
		with self.settings(ANTHROPIC_API_KEY="k"), mock.patch("tools.ai.call", return_value=raw) as call:
			res = self.post({"mode": "summary", "title": "Anti-jamming in LEO", "sections": long})
			body = res.json()
			self.assertEqual(res.status_code, 200, body)
			self.assertEqual(body["fields"][1], {"key": "scenario", "label": "시나리오·네트워크", "value": "시나리오·네트워크 값"})
			sent = call.call_args.kwargs["content"]
			self.assertLessEqual(len(sent), 4000)  # 회원 한도(4000자) 안으로 줄여서 보냄
			self.assertIn("## system", sent)
			again = self.post({"mode": "summary", "title": "Anti-jamming in LEO", "sections": long}).json()
		self.assertEqual(call.call_count, 1)  # 같은 논문은 저장된 결과
		self.assertTrue(again["cached"])

	def test_repair_leaked_fields(self):
		from . import paper_ai
		raw = {"threat": 'TDOA.</threat>\n<parameter name="objective">LEP 최대화</objective>\n<parameter name="method">SAA</parameter>', "objective": "언급 없음", "method": "", "metrics": "LEP"}
		self.assertEqual(paper_ai.repair(raw, {"threat", "objective", "method", "metrics"}), {"threat": "TDOA.", "objective": "LEP 최대화", "method": "SAA", "metrics": "LEP"})

	def test_intro_and_group(self):
		from unittest import mock
		self.client.force_login(self.user)
		raw = {"paragraphs": [{"n": 1, "role": "background", "gist": "배경"}, {"n": 9, "role": "gap", "gist": "없는 문단"}, {"n": 2, "role": "weird", "gist": "기여"}],
			   "flow": "배경 → 기여", "lessons": ["짧게 시작"], "phrases": ["Motivated by ..., we ..."]}
		with self.settings(ANTHROPIC_API_KEY="k"), mock.patch("tools.ai.call", return_value=raw):
			body = self.post({"mode": "intro", "title": "T", "paragraphs": ["p1", "p2"]}).json()
		self.assertEqual([p["n"] for p in body["paragraphs"]], [1, 2])  # 없는 문단 번호는 버림
		self.assertEqual(body["paragraphs"][1]["role"], "background")  # 이상한 역할은 기본값
		self.assertEqual(self.post({"mode": "group", "papers": [{"title": "A", "fields": []}]}).status_code, 400)
		graw = {"groups": [{"name": "DRL", "papers": [1, 2, 7], "common": "c", "differences": "d"}], "gaps": [{"gap": "g", "why": "w"}], "overview": "o"}
		with self.settings(ANTHROPIC_API_KEY="k"), mock.patch("tools.ai.call", return_value=graw):
			g = self.post({"mode": "group", "papers": [{"title": "A", "fields": [{"key": "method", "value": "DRL"}]}, {"title": "B", "fields": []}]}).json()
		self.assertEqual(g["groups"][0]["papers"], [1, 2])


class PaperTranslateTests(TestCase):
	def setUp(self):
		from django.contrib.auth import get_user_model
		from django.core.cache import cache
		cache.clear()
		self.user = get_user_model().objects.create_user("u", "u@example.com", "pw")

	def test_translate(self):
		import json
		from unittest import mock
		post = lambda body: self.client.post("/tools/papers/ai/", json.dumps(body), content_type="application/json")
		self.client.force_login(self.user)
		items = [{"i": 0, "text": "We consider a LEO satellite ⟦m0⟧ [⟦c1⟧]."}, {"i": 1, "text": "System Model"}]
		raw = {"items": [{"i": 0, "ko": "LEO 위성 ⟦m0⟧ 를 고려한다 [⟦c1⟧]."}, {"i": 1, "ko": "시스템 모델"}, {"i": 9, "ko": "없는 번호"}]}
		with self.settings(ANTHROPIC_API_KEY="k"), mock.patch("tools.ai.call", return_value=raw) as call:
			body = post({"mode": "translate", "title": "T", "items": items}).json()
			again = post({"mode": "translate", "title": "T", "items": items}).json()
		self.assertEqual([x["i"] for x in body["items"]], [0, 1])
		self.assertIn("⟦m0⟧", body["items"][0]["ko"])
		self.assertIn("[0] We consider", call.call_args.kwargs["content"])
		self.assertEqual(call.call_count, 1)  # 같은 글은 저장된 번역
		self.assertTrue(again["cached"])
		too_long = [{"i": 0, "text": "x" * 5000}]
		with self.settings(ANTHROPIC_API_KEY="k"):
			self.assertEqual(post({"mode": "translate", "items": too_long}).status_code, 400)  # 회원 4000자 넘으면 나눠 보내라고
