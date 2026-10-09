import json
import urllib.error
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import ai
from .models import AIUsage
from .permissions import AI_LIMITS, FRIEND_STREAM_LIMITS, MEMBER_STREAM_LIMITS, is_friend, set_friend, stream_limits, tier


def fake_reply(payload, inp=1000, out=500):
	return {"content": [{"type": "tool_use", "input": payload}], "usage": {"input_tokens": inp, "output_tokens": out}}


@override_settings(ANTHROPIC_API_KEY="k", AI_DAILY_BUDGET_USD=1.0, AI_PRICE_INPUT_PER_MTOK=1.0, AI_PRICE_OUTPUT_PER_MTOK=5.0)
class AITests(TestCase):
	def setUp(self):
		cache.clear()
		User = get_user_model()
		self.member = User.objects.create_user("member", "m@example.com", "pw-for-tests-only")
		self.friend = User.objects.create_user("friend", "f@example.com", "pw-for-tests-only")
		set_friend(self.friend, True)
		self.admin = User.objects.create_superuser("admin", "a@example.com", "pw-for-tests-only")

	def fresh(self, user):
		return get_user_model().objects.get(pk=user.pk)  # 등급 캐시 없이 다시

	def test_tiers(self):
		from django.contrib.auth.models import AnonymousUser
		self.assertEqual([tier(AnonymousUser()), tier(self.member), tier(self.fresh(self.friend)), tier(self.admin)], ["anon", "member", "friend", "admin"])
		self.assertEqual(stream_limits(self.fresh(self.friend)), FRIEND_STREAM_LIMITS)
		self.assertEqual(stream_limits(self.member), MEMBER_STREAM_LIMITS)
		set_friend(self.friend, False)
		self.assertFalse(is_friend(self.fresh(self.friend)))

	def test_check_limits_by_tier(self):
		from django.contrib.auth.models import AnonymousUser
		with self.assertRaises(ai.AIError) as e:
			ai.check(AnonymousUser())
		self.assertEqual(e.exception.status, 401)
		with self.assertRaises(ai.AIError) as e:
			ai.check(self.member, AI_LIMITS["member"]["max_chars"] + 1)
		self.assertEqual(e.exception.status, 400)
		ai.check(self.fresh(self.friend), AI_LIMITS["member"]["max_chars"] + 1)  # 친한 사람은 더 길게
		AIUsage.objects.bulk_create([AIUsage(user=self.member, feature="regex") for _ in range(AI_LIMITS["member"]["per_day"])])
		AIUsage.objects.create(user=self.member, feature="regex", ok=False)  # 실패는 안 셈
		with self.assertRaises(ai.AIError) as e:
			ai.check(self.member)
		self.assertEqual(e.exception.status, 429)
		# 어제 쓴 건 안 셈
		AIUsage.objects.filter(user=self.member).update(created_at=timezone.now() - timedelta(days=1, hours=1))
		ai.check(self.member)

	def test_site_budget_stops_everyone_but_admin(self):
		AIUsage.objects.create(user=self.admin, feature="diff", cost_usd=Decimal("1.0"))
		for user in (self.member, self.fresh(self.friend)):
			with self.assertRaises(ai.AIError) as e:
				ai.check(user)
			self.assertEqual(e.exception.status, 503)
		ai.check(self.admin)
		self.assertEqual(ai.status(self.member)["reason"], "budget")

	def test_call_records_cost_and_failures(self):
		with mock.patch("tools.ai._post", return_value=fake_reply({"x": 1}, 1_000_000, 100_000)):
			self.assertEqual(ai.call(self.member, "regex", system="s", content="c", tool={"name": "t"}), {"x": 1})
		row = AIUsage.objects.get()
		self.assertEqual((row.input_tokens, row.output_tokens, row.cost_usd, row.tier), (1_000_000, 100_000, Decimal("1.5"), "member"))
		err = urllib.error.HTTPError("u", 529, "busy", {}, None)
		with mock.patch("tools.ai._post", side_effect=err), self.assertRaises(ai.AIError):
			ai.call(self.member, "regex", system="s", content="c", tool={"name": "t"})
		self.assertEqual(AIUsage.objects.filter(ok=False).count(), 1)

	def post(self, name, body):
		return self.client.post(reverse(f"tools:{name}"), json.dumps(body), content_type="application/json")

	def test_regex_ai(self):
		self.assertEqual(self.post("regex_ai", {"prompt": "전화번호"}).status_code, 401)
		self.client.force_login(self.member)
		raw = {"pattern": r"01[016789]-\d{3,4}-\d{4}", "flags": "gxu!", "explanation": "휴대폰 번호", "sample": "010-1234-5678", "caveats": ""}
		with mock.patch("tools.ai._post", return_value=fake_reply(raw)) as post:
			data = self.post("regex_ai", {"prompt": "휴대폰 번호", "sample": "연락처 010-1234-5678"}).json()
		self.assertEqual(data["flags"], "gu")  # 허용된 플래그만
		self.assertEqual(data["pattern"], raw["pattern"])
		self.assertEqual(data["quota"]["remaining"], AI_LIMITS["member"]["per_day"] - 1)
		self.assertIn("010-1234-5678", post.call_args.args[0]["messages"][0]["content"])

	def test_diff_ai(self):
		self.client.force_login(self.fresh(self.friend))
		self.assertEqual(self.post("diff_ai", {"a": "같음", "b": "같음"}).status_code, 400)
		raw = {"summary": "금액이 바뀜", "changes": [{"kind": "수정", "what": "100만원 → 120만원"}, {"kind": "엉뚱", "what": "x"}, {"what": ""}], "watch": ["금액"]}
		with mock.patch("tools.ai._post", return_value=fake_reply(raw)):
			data = self.post("diff_ai", {"a": "100만원", "b": "120만원"}).json()
		self.assertEqual([c["kind"] for c in data["changes"]], ["수정", "수정"])
		self.assertEqual(data["watch"], ["금액"])
		self.assertEqual(data["quota"]["tier"], "friend")

	def test_netcheck_ai(self):
		self.client.force_login(self.member)
		self.assertEqual(self.post("netcheck_ai", {"result": {"type": "evil"}}).status_code, 400)
		raw = {"summary": "22번이 열려 있어요", "findings": [{"level": "bad", "title": "SSH 공개", "detail": "막는 게 좋아요"}, {"level": "??", "title": "t", "detail": "d"}], "next_steps": ["ufw 확인"]}
		with mock.patch("tools.ai._post", return_value=fake_reply(raw)):
			data = self.post("netcheck_ai", {"result": {"type": "port", "host": "1.2.3.4", "ports": [{"port": 22, "open": True}]}}).json()
		self.assertEqual([f["level"] for f in data["findings"]], ["bad", "warn"])

	def test_status_and_studio_page(self):
		self.assertFalse(self.client.get(reverse("tools:ai_status")).json()["enabled"])
		self.client.force_login(self.admin)
		self.assertIsNone(self.client.get(reverse("tools:ai_status")).json()["per_day"])
		AIUsage.objects.create(user=self.member, feature="regex", tier="member", input_tokens=10, output_tokens=5, cost_usd=Decimal("0.0001"))
		res = self.client.get(reverse("studio:ai"), {"days": 30})
		self.assertContains(res, "AI 사용량")
		self.assertContains(res, "정규식 만들기")
		self.client.force_login(self.member)
		self.assertEqual(self.client.get(reverse("studio:ai")).status_code, 302)

	def test_studio_users_friend_toggle(self):
		self.client.force_login(self.admin)
		self.client.post(reverse("studio:users"), {"action": "friend_on", "ids": [self.member.id]})
		self.assertTrue(is_friend(self.fresh(self.member)))
		res = self.client.get(reverse("studio:users"), {"state": "friend"})
		self.assertEqual({u.username for u in res.context["users"]}, {"member", "friend"})
		self.client.post(reverse("studio:users"), {"action": "friend_off", "ids": [self.member.id]})
		self.assertFalse(is_friend(self.fresh(self.member)))

	def test_ocr(self):
		import base64
		self.assertEqual(self.client.get(reverse("tools:ocr")).status_code, 302)
		self.client.force_login(self.member)
		self.assertEqual(self.client.get(reverse("tools:ocr")).status_code, 200)
		img = base64.b64encode(b"\xff\xd8fake-jpeg").decode()
		self.assertEqual(self.post("ocr_run", {"image": img, "type": "image/gif"}).status_code, 400)
		self.assertEqual(self.post("ocr_run", {"image": "@@not-base64@@", "type": "image/jpeg"}).status_code, 400)
		with mock.patch("tools.ai_views.OCR_MAX_BYTES", 5):
			self.assertEqual(self.post("ocr_run", {"image": img, "type": "image/jpeg"}).status_code, 400)  # 너무 큼
		raw = {"text": "회의 안건\n1. 일정", "kind": "손글씨", "unclear": ""}
		with mock.patch("tools.ai._post", return_value=fake_reply(raw)) as post:
			data = self.post("ocr_run", {"image": img, "type": "image/jpeg", "mode": "table"}).json()
		self.assertEqual(data["text"], "회의 안건\n1. 일정")
		content = post.call_args.args[0]["messages"][0]["content"]
		self.assertEqual(content[0]["source"], {"type": "base64", "media_type": "image/jpeg", "data": img})
		self.assertIn("마크다운 표", content[1]["text"])
		self.assertEqual(AIUsage.objects.get().feature, "ocr")
