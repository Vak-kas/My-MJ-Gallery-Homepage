"""QR 코드 AI 스타일 추천 (회원 전용).

사용자가 원하는 분위기를 글로 적으면 Claude 가 QR 꾸미기 옵션(색·점 모양·눈·그라데이션·테두리 문구)을 골라 준다.
- 도구 사용(tool_use)으로 정해진 형식의 값만 받고, 서버에서 한 번 더 검사·보정 (색 대비 등)
- 입력 글·결과는 저장하지 않음
"""

import json
import re
import time
import urllib.error
import urllib.request

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_POST

API_URL = "https://api.anthropic.com/v1/messages"
DAILY_LIMIT = 20
PROMPT_MAX = 200

ENUMS = {
	"shape": ["square", "round", "soft", "diamond", "star", "heart"],
	"grad": ["none", "linear", "diagonal", "radial"],
	"eye": ["square", "rounded", "circle", "leaf"],
	"eyeball": ["square", "rounded", "circle", "leaf"],
	"frame": ["none", "label", "box", "ticket"],
}
COLOR_FIELDS = ["fg", "fg2", "eyec", "eyeballc", "bg", "framec"]
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

TOOL = {
	"name": "apply_qr_style",
	"description": "QR 코드 꾸미기 옵션을 정한다.",
	"input_schema": {
		"type": "object",
		"properties": {
			"name": {"type": "string", "description": "테마 이름 (한국어, 12자 이내)"},
			"reason": {"type": "string", "description": "왜 이렇게 골랐는지 한국어 한 문장"},
			"shape": {"type": "string", "enum": ENUMS["shape"], "description": "점 모양"},
			"fg": {"type": "string", "description": "점 색 #rrggbb (배경보다 확실히 어둡게)"},
			"grad": {"type": "string", "enum": ENUMS["grad"], "description": "점 그라데이션"},
			"fg2": {"type": "string", "description": "그라데이션 두 번째 색 #rrggbb (이것도 배경보다 어둡게)"},
			"eye": {"type": "string", "enum": ENUMS["eye"], "description": "모서리 눈 바깥 모양"},
			"eyeball": {"type": "string", "enum": ENUMS["eyeball"], "description": "모서리 눈 안쪽 모양"},
			"eyec": {"type": "string", "description": "눈 바깥 색 #rrggbb"},
			"eyeballc": {"type": "string", "description": "눈 안쪽 색 #rrggbb (포인트 색으로 써도 됨)"},
			"bg": {"type": "string", "description": "배경 색 #rrggbb (밝은 색)"},
			"frame": {"type": "string", "enum": ENUMS["frame"], "description": "테두리·문구 스타일"},
			"caption": {"type": "string", "description": "테두리 문구 (20자 이내, frame 이 none 이면 빈 문자열)"},
			"framec": {"type": "string", "description": "테두리 색 #rrggbb"},
		},
		"required": ["name", "reason", "shape", "fg", "grad", "fg2", "eye", "eyeball", "eyec", "eyeballc", "bg", "frame", "caption", "framec"],
	},
}

SYSTEM = (
	"너는 QR 코드 디자이너다. 사용자가 원하는 분위기에 맞춰 apply_qr_style 도구로 꾸미기 옵션을 정한다.\n"
	"반드시 지킬 것: 휴대폰 카메라로 잘 찍혀야 한다. 배경은 밝게, 점·눈·그라데이션 색은 모두 배경보다 충분히 어둡게"
	"(명암비 4.5 이상) 한다. 형광·파스텔 점은 피한다. 눈 안쪽 색은 포인트 색으로 써도 되지만 역시 어둡게.\n"
	"사진이 가운데 들어가면 점은 너무 화려하지 않게 한다. 문구는 사용자가 원하면 그 말을, 아니면 분위기에 맞는 짧은 영어나 한국어."
)


def _lum(hex_color):
	r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
	f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
	return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(a, b):
	x, y = sorted((_lum(a), _lum(b)), reverse=True)
	return (x + 0.05) / (y + 0.05)


def _darken(hex_color, k):
	return "#" + "".join(f"{max(0, min(255, round(int(hex_color[i:i + 2], 16) * k))):02x}" for i in (1, 3, 5))


def sanitize(raw):
	"""AI 결과를 허용된 값으로만 정리하고, 잘 찍히도록 색 대비를 보정."""
	out = {}
	for key, allowed in ENUMS.items():
		out[key] = raw.get(key) if raw.get(key) in allowed else allowed[0]
	for key in COLOR_FIELDS:
		value = str(raw.get(key) or "")
		out[key] = value.lower() if HEX.match(value) else None
	out["bg"] = out["bg"] or "#ffffff"
	out["fg"] = out["fg"] or "#1d1d1f"
	if _lum(out["bg"]) < 0.6:  # 배경은 밝게
		out["bg"] = "#ffffff"
	for key in ("fg", "fg2", "eyec", "eyeballc", "framec"):
		color = out[key] or out["fg"]
		for _ in range(12):
			if _contrast(color, out["bg"]) >= 4.5:
				break
			color = _darken(color, 0.85)
		out[key] = color
	out["caption"] = " ".join(str(raw.get("caption") or "").split())[:20]
	if out["frame"] != "none" and not out["caption"]:
		out["caption"] = "SCAN ME"
	out["name"] = " ".join(str(raw.get("name") or "AI 추천").split())[:12]
	out["reason"] = " ".join(str(raw.get("reason") or "").split())[:120]
	return out


def _ask_claude(prompt, has_logo):
	body = {
		"model": settings.ANTHROPIC_MODEL,
		"max_tokens": 600,
		"system": SYSTEM,
		"tools": [TOOL],
		"tool_choice": {"type": "tool", "name": TOOL["name"]},
		"messages": [{"role": "user", "content": f"원하는 분위기: {prompt}\n가운데 사진: {'있음' if has_logo else '없음'}"}],
	}
	req = urllib.request.Request(API_URL, data=json.dumps(body).encode(), method="POST", headers={
		"x-api-key": settings.ANTHROPIC_API_KEY,
		"anthropic-version": "2023-06-01",
		"content-type": "application/json",
	})
	with urllib.request.urlopen(req, timeout=25) as res:
		data = json.loads(res.read().decode())
	for block in data.get("content", []):
		if block.get("type") == "tool_use":
			return block.get("input") or {}
	raise ValueError("no tool_use")


def _limited(user):
	if user.is_superuser:
		return False
	key = f"qr-ai:{user.id}:{time.strftime('%Y-%m-%d')}"
	used = cache.get(key, 0)
	if used >= DAILY_LIMIT:
		return True
	cache.set(key, used + 1, 24 * 60 * 60)
	return False


@require_POST
def qr_ai_style(request):
	if not request.user.is_authenticated:
		return JsonResponse({"error": "AI 추천은 로그인한 회원만 쓸 수 있어요."}, status=401)
	if not settings.ANTHROPIC_API_KEY:
		return JsonResponse({"error": "AI 기능이 아직 설정되지 않았어요."}, status=503)
	try:
		data = json.loads(request.body or b"{}")
	except ValueError:
		return JsonResponse({"error": "요청 형식이 올바르지 않아요."}, status=400)
	prompt = " ".join(str(data.get("prompt") or "").split())[:PROMPT_MAX]
	if len(prompt) < 2:
		return JsonResponse({"error": "원하는 분위기를 적어 주세요."}, status=400)
	if _limited(request.user):
		return JsonResponse({"error": f"AI 추천은 하루 {DAILY_LIMIT}번까지 쓸 수 있어요."}, status=429)
	try:
		style = sanitize(_ask_claude(prompt, bool(data.get("has_logo"))))
	except urllib.error.HTTPError as exc:
		status = 429 if exc.code == 429 else 502
		return JsonResponse({"error": "AI 가 지금 바빠요. 잠시 뒤 다시 시도해 주세요." if status == 429 else "AI 추천을 받지 못했어요."}, status=status)
	except (OSError, ValueError):
		return JsonResponse({"error": "AI 추천을 받지 못했어요. 잠시 뒤 다시 시도해 주세요."}, status=502)
	return JsonResponse(style)
