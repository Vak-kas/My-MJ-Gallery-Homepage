import json
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .meet_views import cleanup_expired
from .models import Meeting, MeetingResponse


class MeetTests(TestCase):
	def setUp(self):
		cache.clear()
		User = get_user_model()
		self.owner = User.objects.create_user("owner", "o@example.com", "pw-for-tests-only")
		self.other = User.objects.create_user("other", "x@example.com", "pw-for-tests-only")
		self.today = timezone.localdate()

	def tearDown(self):
		cache.clear()

	def create(self, **extra):
		self.client.force_login(self.owner)
		days = [(self.today + timedelta(days=i)).isoformat() for i in (1, 2)]
		data = {"title": "캡스톤 회의", "dates": ",".join(days), "start": "540", "end": "720", "slot": "30", **extra}
		resp = self.client.post(reverse("tools:meet"), data)
		self.client.logout()
		return resp

	def post(self, name, meeting, body):
		return self.client.post(reverse(f"tools:meet_{name}", args=[meeting.meet_id]), json.dumps(body), content_type="application/json")

	def test_anonymous_cannot_create_but_can_open_link(self):
		self.assertEqual(self.client.get(reverse("tools:meet")).status_code, 302)
		self.create()
		m = Meeting.objects.get()
		self.assertEqual((m.slots_per_day, m.slot_count), (6, 12))  # 9:00~12:00, 30분 × 2일
		self.assertEqual(timezone.localtime(m.expires_at).date(), self.today + timedelta(days=2 + 15))  # 마지막 날 + 14일이 끝나는 자정
		res = self.client.get(m.get_absolute_url())
		self.assertContains(res, "캡스톤 회의")
		self.assertContains(res, "<title>📅 캡스톤 회의")
		self.assertContains(res, 'name="robots" content="noindex')
		self.assertNotContains(res, "일정 지우기")

	def test_create_validation(self):
		self.create(dates="")
		self.create(start="720", end="540")
		self.create(start="545")  # 칸 단위에 안 맞음
		self.create(dates=(self.today - timedelta(days=10)).isoformat())
		self.create(dates=",".join((self.today + timedelta(days=i)).isoformat() for i in range(40)))
		self.assertFalse(Meeting.objects.exists())

	def test_join_save_and_state(self):
		self.create()
		m = Meeting.objects.get()
		r = self.post("join", m, {"name": "  민 재 ", "pin": "1234"}).json()
		self.assertTrue(r["ok"])
		self.assertEqual(r["name"], "민 재")
		key = r["key"]
		v1 = self.client.get(reverse("tools:meet_state", args=[m.meet_id])).json()["version"]
		saved = self.post("save", m, {"key": key, "slots": [0, 1, 1, 5, 11, 12, -1, "x"]})
		self.assertEqual(saved.status_code, 400)  # 이상한 값이 섞이면 거절
		self.assertTrue(self.post("save", m, {"key": key, "slots": [0, 1, 1, 5, 11, 12, 99]}).json()["ok"])
		state = self.client.get(reverse("tools:meet_state", args=[m.meet_id]), {"v": v1}).json()
		self.assertNotIn("same", state)
		self.assertEqual(state["responses"], [{"id": r["id"], "name": "민 재", "slots": [0, 1, 5, 11]}])  # 범위 밖 칸은 버림
		same = self.client.get(reverse("tools:meet_state", args=[m.meet_id]), {"v": state["version"]}).json()
		self.assertTrue(same.get("same"))
		# 키 없이 저장은 안 됨
		self.assertEqual(self.post("save", m, {"key": "wrong", "slots": [2]}).status_code, 403)

	def test_same_name_needs_key_or_pin(self):
		self.create()
		m = Meeting.objects.get()
		with_pin = self.post("join", m, {"name": "가", "pin": "9999"}).json()
		self.post("join", m, {"name": "나"})
		self.assertEqual(self.post("join", m, {"name": "가"}).status_code, 403)
		self.assertEqual(self.post("join", m, {"name": "가", "pin": "0000"}).status_code, 403)
		again = self.post("join", m, {"name": "가", "pin": "9999"}).json()  # 다른 기기에서 비밀번호로
		self.assertTrue(again["ok"])
		self.assertNotEqual(again["key"], with_pin["key"])
		self.assertEqual(self.post("join", m, {"name": "나", "pin": "x"}).status_code, 403)  # 비밀번호 없이 만든 이름은 가로챌 수 없음
		self.assertTrue(self.post("join", m, {"name": "가", "key": again["key"]}).json()["ok"])
		self.assertEqual(MeetingResponse.objects.count(), 2)

	def test_remove_rules(self):
		self.create()
		m = Meeting.objects.get()
		a = self.post("join", m, {"name": "가"}).json()
		b = self.post("join", m, {"name": "나"}).json()
		self.assertEqual(self.post("remove", m, {"id": b["id"]}).status_code, 403)  # 남이 남을 못 뺌
		self.client.force_login(self.other)
		self.assertEqual(self.post("remove", m, {"id": b["id"]}).status_code, 403)
		self.client.force_login(self.owner)
		self.assertTrue(self.post("remove", m, {"id": b["id"]}).json()["ok"])  # 만든 사람은 뺄 수 있음
		self.client.logout()
		self.assertTrue(self.post("remove", m, {"key": a["key"]}).json()["ok"])  # 본인은 나갈 수 있음
		self.assertFalse(MeetingResponse.objects.exists())

	def test_delete_only_owner_and_cleanup(self):
		self.create()
		m = Meeting.objects.get()
		self.client.force_login(self.other)
		self.assertEqual(self.client.post(reverse("tools:meet_delete", args=[m.meet_id])).status_code, 404)
		Meeting.objects.filter(pk=m.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
		self.assertEqual(self.client.get(m.get_absolute_url()).status_code, 404)
		self.assertEqual(cleanup_expired(), 1)

	def test_join_rate_limit_and_capacity(self):
		self.create()
		m = Meeting.objects.get()
		with mock.patch("tools.meet_views.MAX_RESPONSES", 2):
			self.post("join", m, {"name": "1"})
			self.post("join", m, {"name": "2"})
			self.assertEqual(self.post("join", m, {"name": "3"}).status_code, 403)
		with mock.patch("tools.meet_views.JOIN_LIMIT", (3, 600)):
			cache.clear()
			codes = [self.post("join", m, {"name": f"r{i}"}).status_code for i in range(4)]
		self.assertEqual(codes[-1], 429)
