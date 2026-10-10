"""웹훅 · 요청 확인기 (만들기·보기는 회원, 주소로 요청 보내기는 누구나).

/hook/<bin_id>[/아무 경로] 로 오는 요청(방식·헤더·본문)을 기록하고 정해 둔 답을 돌려줌.
- 쿠키는 기록하지 않음 (이 사이트에 로그인한 브라우저로 주소를 열면 로그인 쿠키가 같이 오기 때문)
- 답은 JSON·글만, nosniff + CSP sandbox 로 내려줘서 이 주소로 HTML 페이지를 띄울 수 없음
"""

import base64
import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db.models import F
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from security.utils import client_ip

from .link_views import _absolute
from .models import HookBin, HookRequest
from .permissions import tier

HOOK_LIMITS = {
	"member": {"bins": 5, "keep": 200},
	"vip": {"bins": 20, "keep": 1000},
	"admin": {"bins": None, "keep": 1000},
}
TTL_DAYS = {"1": 1, "7": 7, "30": 30}
MAX_BODY_STORE = 256 * 1024  # 본문은 앞 256KB 까지만 저장
MAX_RESPONSE_BODY = 4000
RATE_PER_MIN = 120  # 주소 하나에 1분 동안 받을 수 있는 요청 수
DROP_HEADERS = {"cookie", "x-real-ip", "x-forwarded-for", "x-forwarded-proto", "x-forwarded-host", "x-forwarded-port"}


def _limits(user):
	return HOOK_LIMITS.get(tier(user), HOOK_LIMITS["member"])


def _cleanup():
	HookBin.objects.filter(expires_at__lte=timezone.now()).delete()


def _hook_url(request, hook):
	return _absolute(request, f"/hook/{hook.bin_id}")


def _own_bin(request, bin_id):
	hook = HookBin.objects.filter(bin_id=bin_id, owner=request.user, expires_at__gt=timezone.now()).first()
	if not hook:
		raise Http404
	return hook


# ── 요청 받기 ─────────────────────────────

def _headers(request):
	out = []
	for key, value in request.META.items():
		if key.startswith("HTTP_"):
			name = key[5:]
		elif key in ("CONTENT_TYPE", "CONTENT_LENGTH"):
			name = key
		else:
			continue
		name = "-".join(p.capitalize() for p in name.split("_"))
		if name.lower() in DROP_HEADERS or (name in ("Content-Type", "Content-Length") and not value):
			continue
		out.append([name, str(value)[:2000]])
	out.sort(key=lambda h: h[0].lower())
	return out[:100]


def _plain(text, status, ctype="text/plain"):
	res = HttpResponse(text, status=status, content_type=f"{ctype}; charset=utf-8")
	res["X-Content-Type-Options"] = "nosniff"
	res["Content-Security-Policy"] = "sandbox; default-src 'none'"
	res["X-Robots-Tag"] = "noindex"
	res["Access-Control-Allow-Origin"] = "*"  # 브라우저 fetch 로 시험해도 답을 읽을 수 있게 (쿠키는 안 받음)
	res["Access-Control-Allow-Methods"] = "*"
	res["Access-Control-Allow-Headers"] = "*"
	return res


@csrf_exempt
def hook_receive(request, bin_id, rest=""):
	hook = HookBin.objects.filter(bin_id=bin_id, expires_at__gt=timezone.now()).first()
	if not hook:
		return _plain('{"error": "없거나 만료된 주소예요."}\n', 404, "application/json")
	rate_key = f"hook:rate:{hook.pk}:{int(timezone.now().timestamp() // 60)}"
	if cache.get_or_set(rate_key, 0, 70) >= RATE_PER_MIN:
		return _plain('{"error": "요청이 너무 많아요. 잠시 뒤 다시 보내 주세요."}\n', 429, "application/json")
	cache.incr(rate_key)

	raw = request.read(MAX_BODY_STORE + 1)
	try:
		size = max(int(request.META.get("CONTENT_LENGTH") or 0), len(raw))
	except ValueError:
		size = len(raw)
	truncated = len(raw) > MAX_BODY_STORE or size > len(raw)
	raw = raw[:MAX_BODY_STORE]
	try:
		body, is_b64 = raw.decode("utf-8"), False
		if "\x00" in body:
			raise UnicodeDecodeError("utf-8", raw, 0, 1, "nul")
	except UnicodeDecodeError:
		body, is_b64 = base64.b64encode(raw).decode(), True

	HookRequest.objects.create(
		bin=hook,
		method=request.method[:12],
		path=(rest or "")[:500],
		query=request.META.get("QUERY_STRING", "")[:4000],
		headers=_headers(request),
		body=body,
		body_base64=is_b64,
		body_size=size,
		truncated=truncated,
		content_type=(request.META.get("CONTENT_TYPE") or "")[:200],
		ip=client_ip(request),
	)
	HookBin.objects.filter(pk=hook.pk).update(request_count=F("request_count") + 1)
	# 오래된 것부터 지워서 주소마다 정해진 개수만 남김
	keep = _limits(hook.owner)["keep"]
	old = list(HookRequest.objects.filter(bin=hook).values_list("id", flat=True)[keep:keep + 500])
	if old:
		HookRequest.objects.filter(id__in=old).delete()

	if request.method == "HEAD":
		return _plain("", hook.response_status)
	ctype = "application/json" if hook.response_type == "json" else "text/plain"
	return _plain(hook.response_body, hook.response_status, ctype)


# ── 만든 사람 화면 ─────────────────────────────

@login_required
def webhook_page(request):
	_cleanup()
	lim = _limits(request.user)
	bins = HookBin.objects.filter(owner=request.user)
	if request.method == "POST":
		if lim["bins"] is not None and bins.count() >= lim["bins"]:
			messages.error(request, f"주소는 {lim['bins']}개까지 만들 수 있어요. 안 쓰는 걸 지워 주세요.")
			return redirect("tools:webhook")
		days = TTL_DAYS.get(request.POST.get("ttl", "7"), 7)
		hook = HookBin.objects.create(
			owner=request.user,
			name=" ".join((request.POST.get("name") or "").split())[:60],
			expires_at=timezone.now() + timedelta(days=days),
		)
		return redirect("tools:webhook_bin", bin_id=hook.bin_id)
	rows = [{"obj": b, "url": _hook_url(request, b)} for b in bins]
	return render(request, "tools/webhook.html", {"rows": rows, "max_bins": lim["bins"], "keep": lim["keep"]})


@login_required
def webhook_bin(request, bin_id):
	hook = _own_bin(request, bin_id)
	return render(request, "tools/webhook_bin.html", {
		"hook": hook,
		"hook_url": _hook_url(request, hook),
		"keep": _limits(request.user)["keep"],
		"max_kb": MAX_BODY_STORE // 1024,
	})


def _summary(r):
	return {
		"id": r.id, "method": r.method, "path": r.path, "query": r.query, "size": r.body_size,
		"content_type": r.content_type, "ip": r.ip or "", "at": r.created_at.isoformat(),
	}


@login_required
def webhook_requests(request, bin_id):
	"""새로 온 요청 목록 (after 보다 큰 id 만). 화면이 2초마다 부름."""
	hook = _own_bin(request, bin_id)
	qs = hook.requests.all()
	try:
		after = int(request.GET.get("after") or 0)
	except ValueError:
		after = 0
	if after:
		qs = qs.filter(id__gt=after)
	items = [_summary(r) for r in qs[:100]]
	return JsonResponse({"items": items, "count": hook.request_count})


@login_required
def webhook_request_detail(request, bin_id, req_id):
	hook = _own_bin(request, bin_id)
	r = get_object_or_404(HookRequest, bin=hook, id=req_id)
	return JsonResponse({
		**_summary(r), "headers": r.headers, "body": r.body, "body_base64": r.body_base64, "truncated": r.truncated,
	})


@login_required
@require_POST
def webhook_settings(request, bin_id):
	hook = _own_bin(request, bin_id)
	try:
		data = json.loads(request.body or b"{}")
		status = int(data.get("status") or 200)
	except ValueError:
		return JsonResponse({"error": "요청 형식이 올바르지 않아요."}, status=400)
	if not 200 <= status <= 599:
		return JsonResponse({"error": "응답 코드는 200~599 사이로 넣어 주세요."}, status=400)
	body = str(data.get("body") or "")
	if len(body) > MAX_RESPONSE_BODY:
		return JsonResponse({"error": f"응답 본문은 {MAX_RESPONSE_BODY:,}자까지예요."}, status=400)
	rtype = "text" if data.get("type") == "text" else "json"
	if rtype == "json" and body.strip():
		try:
			json.loads(body)
		except ValueError:
			return JsonResponse({"error": "JSON 형식이 아니에요. '글'로 바꾸거나 고쳐 주세요."}, status=400)
	hook.name = " ".join(str(data.get("name") or "").split())[:60]
	hook.response_status, hook.response_type, hook.response_body = status, rtype, body
	hook.save(update_fields=["name", "response_status", "response_type", "response_body"])
	return JsonResponse({"ok": True})


@login_required
@require_POST
def webhook_clear(request, bin_id):
	hook = _own_bin(request, bin_id)
	hook.requests.all().delete()
	return JsonResponse({"ok": True})


@login_required
@require_POST
def webhook_delete(request, bin_id):
	hook = get_object_or_404(HookBin, bin_id=bin_id, owner=request.user)
	hook.delete()
	messages.success(request, "주소를 지웠어요. 이제 이 주소로 오는 요청은 404 를 받아요.")
	return redirect(reverse("tools:webhook"))
