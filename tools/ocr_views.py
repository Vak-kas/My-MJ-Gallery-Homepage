"""사진 글자 추출 — 무료(서버의 Tesseract). 더 정확한 AI 읽기는 ai_views.ocr_ai.

서버 CPU 를 쓰므로 10분 횟수 제한 + 프로세스마다 한 번에 하나씩만 처리.
"""

import base64
import binascii
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from io import BytesIO

from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from PIL import Image, ImageOps, UnidentifiedImageError

from security.utils import client_ip

from .permissions import quota_multiplier, tier

MAX_BYTES = 4 * 1024 * 1024
MAX_PIXELS = 25_000_000
WINDOW = 10 * 60
LIMITS = {"anon": 10, "member": 30, "vip": 30, "admin": None}  # 10분에 몇 장 (VIP 회원은 배수)
_busy = threading.BoundedSemaphore(1)


def _error(message, status=400):
	return JsonResponse({"error": message}, status=status)


def _limited(request):
	t = tier(request.user)
	limit = LIMITS[t]
	if limit is None:
		return False
	limit *= quota_multiplier(request.user)
	who = f"u{request.user.id}" if request.user.is_authenticated else f"ip{client_ip(request)}"
	key = f"ocr-free:{who}"
	now = time.time()
	bucket = cache.get(key)
	if not bucket or now - bucket["start"] >= WINDOW:
		bucket = {"start": now, "count": 0}
	if bucket["count"] >= limit:
		return True
	bucket["count"] += 1
	cache.set(key, bucket, max(1, int(bucket["start"] + WINDOW - now)))
	return False


def prepare(raw):
	img = Image.open(BytesIO(raw))
	if img.width * img.height > MAX_PIXELS:
		raise ValueError("사진이 너무 커요.")
	img = ImageOps.exif_transpose(img).convert("L")
	img = ImageOps.autocontrast(img)
	long_side = max(img.size)
	if long_side < 2000:  # 작은 글자는 키우면 훨씬 잘 읽음
		scale = min(1.5, 3000 / long_side)
		img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
	return img


def to_text(txt, tsv, mode):
	"""Tesseract 가 만든 글(띄어쓰기는 이게 정확함)을 줄·문단 모양으로, 평균 신뢰도(0~100)는 tsv 에서."""
	paras = [p.strip("\n") for p in txt.replace("\x0c", "").split("\n\n")]
	paras = ["\n".join(line.rstrip() for line in p.splitlines() if line.strip()) for p in paras]
	paras = [p for p in paras if p]
	if mode == "para":
		paras = [" ".join(p.splitlines()) for p in paras]
	confs = []
	for row in tsv.splitlines()[1:]:
		cols = row.split("\t")
		if len(cols) >= 12 and cols[11].strip():
			try:
				conf = float(cols[10])
			except ValueError:
				continue
			if conf >= 0:
				confs.append(conf)
	return "\n\n".join(paras), round(sum(confs) / len(confs)) if confs else 0


def run_tesseract(img):
	"""tesseract 를 한 번 실행해 글(txt)과 낱말별 신뢰도(tsv)를 같이 받음."""
	with tempfile.TemporaryDirectory() as tmp:
		src = os.path.join(tmp, "in.png")
		img.save(src)
		base = os.path.join(tmp, "out")
		subprocess.run(
			["tesseract", src, base, "-l", "kor+eng", "--oem", "1", "--psm", "6", "-c", "preserve_interword_spaces=1", "txt", "tsv"],
			check=True, capture_output=True, timeout=20,
		)
		with open(base + ".txt", encoding="utf-8") as f:
			txt = f.read()
		with open(base + ".tsv", encoding="utf-8") as f:
			tsv = f.read()
	return txt, tsv


@require_POST
def ocr_free(request):
	try:
		body = json.loads(request.body or b"{}")
		raw = base64.b64decode(str(body.get("image") or ""), validate=True)
	except (ValueError, binascii.Error):
		return _error("사진을 읽지 못했어요.")
	if not raw or len(raw) > MAX_BYTES:
		return _error("사진이 너무 커요. (4MB 까지)")
	mode = body.get("mode") if body.get("mode") in {"lines", "para"} else "lines"
	if not shutil.which("tesseract"):
		return _error("서버에 무료 글자 인식 엔진이 없어요. ✨ AI 로 읽어 주세요.", 503)
	if _limited(request):
		return _error("무료 읽기는 10분에 몇 장까지만 돼요. 잠시 뒤 다시 하거나 ✨ AI 로 읽어 주세요.", 429)
	if not _busy.acquire(timeout=8):
		return _error("지금 다른 사진을 읽는 중이에요. 잠시 뒤 다시 시도해 주세요.", 503)
	started = time.monotonic()
	try:
		txt, tsv = run_tesseract(prepare(raw))
	except ValueError as exc:
		return _error(str(exc))
	except (UnidentifiedImageError, Image.DecompressionBombError):
		return _error("사진을 열지 못했어요.")
	except subprocess.TimeoutExpired:
		return _error("글자가 너무 많아 시간이 오래 걸려요. ✨ AI 로 읽어 주세요.", 503)
	except (OSError, subprocess.CalledProcessError):
		return _error("무료 글자 인식에 실패했어요. ✨ AI 로 읽어 주세요.", 503)
	finally:
		_busy.release()
	text, conf = to_text(txt, tsv, mode)
	return JsonResponse({"text": text[:20000], "conf": conf, "engine": "free", "seconds": round(time.monotonic() - started, 1)})
