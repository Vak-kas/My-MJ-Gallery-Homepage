import base64
import json
from io import BytesIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from PIL import Image

from .ocr_views import to_text


def png_b64(size=(300, 120)):
	buf = BytesIO()
	Image.new("RGB", size, "white").save(buf, "PNG")
	return base64.b64encode(buf.getvalue()).decode()


TXT = "캡스톤 2차 회의록\n\n결정 사항: 백엔드는\nDjango 로 한다.\n\x0c"
TSV = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n" + "\n".join(
	f"5\t1\t1\t1\t1\t{i}\t0\t0\t10\t10\t{c}\t{w}" for i, (c, w) in enumerate([(90, "캡스톤"), (80, "2차"), (-1, ""), (70, "회의록")], 1))


class FreeOCRTests(TestCase):
	def setUp(self):
		cache.clear()

	def tearDown(self):
		cache.clear()

	def run_ocr(self, mode="lines"):
		with mock.patch("tools.ocr_views.shutil.which", return_value="/usr/bin/tesseract"), \
				mock.patch("tools.ocr_views.run_tesseract", return_value=(TXT, TSV)) as fake:
			res = self.client.post(reverse("tools:ocr_free"), json.dumps({"image": png_b64(), "mode": mode}), content_type="application/json")
		return res, fake

	def test_to_text_lines_and_paragraphs(self):
		self.assertEqual(to_text(TXT, TSV, "lines"), ("캡스톤 2차 회의록\n\n결정 사항: 백엔드는\nDjango 로 한다.", 80))
		self.assertEqual(to_text(TXT, TSV, "para")[0], "캡스톤 2차 회의록\n\n결정 사항: 백엔드는 Django 로 한다.")

	def test_anonymous_can_read_and_small_images_are_enlarged(self):
		self.assertEqual(self.client.get(reverse("tools:ocr")).status_code, 200)
		res, fake = self.run_ocr()
		self.assertEqual(res.status_code, 200)
		self.assertEqual(res.json()["engine"], "free")
		img = fake.call_args.args[0]
		self.assertEqual((img.mode, img.size), ("L", (450, 180)))  # 흑백 + 1.5배
		self.assertEqual(res.json()["conf"], 80)

	def test_bad_input(self):
		post = lambda body: self.client.post(reverse("tools:ocr_free"), json.dumps(body), content_type="application/json")
		self.assertEqual(post({"image": "@@"}).status_code, 400)
		self.assertEqual(post({"image": base64.b64encode(b"not an image").decode()}).status_code, 400)

	def test_rate_limit_by_tier(self):
		codes = [self.run_ocr()[0].status_code for _ in range(11)]
		self.assertEqual(codes[-1], 429)  # 비로그인 10분 10장
		admin = get_user_model().objects.create_superuser("admin", "a@example.com", "pw-for-tests-only")
		self.client.force_login(admin)
		self.assertEqual(self.run_ocr()[0].status_code, 200)  # 관리자는 제한 없음

	def test_engine_missing_or_failing(self):
		post = lambda: self.client.post(reverse("tools:ocr_free"), json.dumps({"image": png_b64()}), content_type="application/json")
		with mock.patch("tools.ocr_views.shutil.which", return_value=None):
			self.assertEqual(post().status_code, 503)
		import subprocess
		with mock.patch("tools.ocr_views.shutil.which", return_value="/usr/bin/tesseract"), \
				mock.patch("tools.ocr_views.run_tesseract", side_effect=subprocess.TimeoutExpired("tesseract", 20)):
			self.assertEqual(post().status_code, 503)


class VipGroupMigrationTests(TestCase):
	def test_old_friends_group_renamed(self):
		from importlib import import_module

		from django.apps import apps
		from django.contrib.auth.models import Group

		user = get_user_model().objects.create_user("u", "u@example.com", "pw-for-tests-only")
		Group.objects.create(name="friends").user_set.add(user)
		import_module("tools.migrations.0007_rename_friends_group_to_vip").forward(apps, None)
		self.assertEqual(list(Group.objects.values_list("name", flat=True)), ["vip"])
		self.assertTrue(user.groups.filter(name="vip").exists())


class RealTesseractTests(TestCase):
	"""tesseract 가 깔린 곳(서버·로컬)에서만 실제로 돌려 봄."""

	def test_reads_korean_with_spacing(self):
		import shutil
		import unittest

		if not shutil.which("tesseract"):
			raise unittest.SkipTest("tesseract 없음")
		from pathlib import Path

		from django.conf import settings
		from PIL import ImageDraw, ImageFont

		from .ocr_views import prepare, run_tesseract

		font = ImageFont.truetype(str(Path(settings.BASE_DIR) / "blog/fonts/NanumGothic-Bold.ttf"), 40)
		img = Image.new("RGB", (900, 120), "white")
		ImageDraw.Draw(img).text((20, 30), "캡스톤 회의는 10월 20일", font=font, fill="black")
		buf = BytesIO()
		img.save(buf, "PNG")
		text, conf = to_text(*run_tesseract(prepare(buf.getvalue())), "lines")
		self.assertIn("캡스톤", text)
		self.assertIn("10월 20일", text)
		self.assertGreater(conf, 50)
