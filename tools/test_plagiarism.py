import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import AIUsage
from .papers import PaperError
from .permissions import PLAGIARISM_PAPER_LIMITS, PLAGIARISM_SENTENCES
from .test_ai import fake_reply

LONG = "Multipath fading occurs when a radio signal reaches the receiver through several reflected paths at different times."


def work(i, abstract="We study multipath fading and OFDM in wireless channels."):
	words = abstract.split()
	return {
		"id": f"https://openalex.org/W{i}", "title": f"Paper {i}", "publication_year": 2020,
		"authorships": [{"author": {"display_name": "Kim"}}], "doi": f"https://doi.org/10.1/{i}",
		"abstract_inverted_index": {w: [k] for k, w in enumerate(words)},
		"primary_location": {"source": {"display_name": "IEEE Access", "id": "S1"}},
	}


class PlagiarismPapersTests(TestCase):
	def setUp(self):
		cache.clear()
		self.member = get_user_model().objects.create_user("member", "m@example.com", "pw-for-tests-only")
		self.url = reverse("tools:plagiarism_papers")

	def post(self, sentences):
		return self.client.post(self.url, json.dumps({"sentences": sentences}), content_type="application/json")

	def test_page_is_public_and_mentions_privacy(self):
		res = self.client.get(reverse("tools:plagiarism"))
		self.assertContains(res, "서버로 올라가지 않아요")
		self.assertContains(res, "로그인하면 쓸 수 있어요")

	def test_papers_need_login(self):
		self.assertEqual(self.post([LONG]).status_code, 401)

	def test_finds_papers_dedupes_and_counts_quota(self):
		self.client.force_login(self.member)
		with mock.patch("tools.plagiarism._openalex", return_value={"results": [work(1), work(2)]}) as oa:
			res = self.post([LONG, LONG + " Again.", "too short"] + [LONG + str(i) for i in range(10)])
		data = res.json()
		self.assertEqual(res.status_code, 200)
		self.assertEqual([p["title"] for p in data["papers"]], ["Paper 1", "Paper 2"])  # 같은 논문은 한 번만
		self.assertEqual(len(data["sentences"]), PLAGIARISM_SENTENCES)  # 짧은 문장 빼고 최대 N개
		self.assertEqual(data["papers"][0]["found_by"], list(range(PLAGIARISM_SENTENCES)))
		self.assertIn("multipath", data["papers"][0]["abstract"])
		self.assertEqual(data["left"], PLAGIARISM_PAPER_LIMITS["member"] - 1)
		# 검색어엔 기호 없이 단어만
		self.assertNotIn(".", oa.call_args_list[0].args[0]["search"])

	def test_same_sentence_is_cached_and_limit_enforced(self):
		self.client.force_login(self.member)
		with mock.patch("tools.plagiarism._openalex", return_value={"results": [work(1)]}) as oa:
			for _ in range(PLAGIARISM_PAPER_LIMITS["member"]):
				self.assertEqual(self.post([LONG]).status_code, 200)
			self.assertEqual(oa.call_count, 1)  # 같은 문장은 하루 캐시
			res = self.post([LONG])
		self.assertEqual(res.status_code, 429)
		self.assertIn("하루", res.json()["error"])

	def test_openalex_error_is_shown(self):
		self.client.force_login(self.member)
		with mock.patch("tools.plagiarism._openalex", side_effect=PaperError("오늘 쓸 수 있는 논문 검색량을 다 썼어요.", 503)):
			res = self.post([LONG])
		self.assertEqual(res.status_code, 503)
		self.assertIn("검색량", res.json()["error"])


@override_settings(ANTHROPIC_API_KEY="k", AI_DAILY_BUDGET_USD=1.0, AI_PRICE_INPUT_PER_MTOK=1.0, AI_PRICE_OUTPUT_PER_MTOK=5.0)
class PlagiarismAITests(TestCase):
	A = "무선 통신에서 다중 경로 페이딩은 신호가 여러 경로로 반사되어 수신기에 서로 다른 시간에 도착하면서 생기는 현상이다. 그래서 세기가 변한다."
	B = "신호가 여러 갈래로 반사돼 수신기에 제각각 다른 시각에 닿으면서 나타나는 것이 무선 통신의 다중 경로 페이딩이다. 세기도 바뀐다."

	def setUp(self):
		cache.clear()
		self.member = get_user_model().objects.create_user("member", "m@example.com", "pw-for-tests-only")
		self.url = reverse("tools:plagiarism_ai")

	def post(self, a=None, b=None):
		return self.client.post(self.url, json.dumps({"a": a or self.A, "b": b or self.B, "label_a": "과제", "label_b": "원본"}), content_type="application/json")

	def test_needs_login(self):
		res = self.post()
		self.assertEqual(res.status_code, 401)

	def test_reports_pairs_and_checks_quotes_exist(self):
		self.client.force_login(self.member)
		reply = fake_reply({
			"verdict": "높음", "score": 85, "summary": "어순과 단어만 바꿨어요.",
			"pairs": [
				{"a_quote": "다중 경로 페이딩은 신호가 여러 경로로 반사되어", "b_quote": "신호가 여러 갈래로 반사돼", "kind": "말 바꾸기", "note": "동의어"},
				{"a_quote": "지어낸 문장이에요", "b_quote": "신호가 여러 갈래로 반사돼", "kind": "엉뚱한 종류", "note": "x"},
			],
		})
		with mock.patch("tools.ai._post", return_value=reply) as post:
			res = self.post()
		data = res.json()
		self.assertEqual(res.status_code, 200)
		self.assertEqual((data["verdict"], data["score"]), ("높음", 85))
		self.assertTrue(data["pairs"][0]["verified"])
		self.assertFalse(data["pairs"][1]["verified"])  # 원문에 없는 인용은 확인 안 됨
		self.assertEqual(data["pairs"][1]["kind"], "말 바꾸기")
		self.assertIn("과제", post.call_args.args[0]["messages"][0]["content"])
		self.assertEqual(AIUsage.objects.get().feature, "plagiarism")
		self.assertEqual(data["quota"]["used"], 1)

	def test_rejects_short_or_identical(self):
		self.client.force_login(self.member)
		with mock.patch("tools.ai._post") as post:
			self.assertIn("50자", self.post(a="짧아요" * 3).json()["error"])
			self.assertIn("똑같아요", self.post(a=self.A, b=self.A + "  ").json()["error"])
		post.assert_not_called()

	def test_member_char_limit(self):
		self.client.force_login(self.member)
		res = self.post(a="가" * 3000, b="나" * 3000)
		self.assertEqual(res.status_code, 400)
		self.assertIn("자까지", res.json()["error"])
