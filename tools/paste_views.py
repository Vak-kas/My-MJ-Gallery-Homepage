"""코드 붙여넣기 공유 (만들기는 회원, 링크가 있으면 누구나 봄).

목록·검색에 나오지 않는 링크 공유. 원본(raw)은 text/plain + nosniff + sandbox 로만 내려줘서
누가 HTML·스크립트를 올려도 이 사이트에서 실행되지 않음.
"""

import json
import re
from datetime import timedelta
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import F
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .link_views import _absolute
from .models import Paste
from .permissions import tier

# 등급별: 한 개 최대 크기(바이트), 남겨 둘 수 있는 개수
PASTE_LIMITS = {
	"member": {"max_bytes": 512 * 1024, "max_count": 100},
	"vip": {"max_bytes": 2 * 1024 * 1024, "max_count": 500},
	"admin": {"max_bytes": 2 * 1024 * 1024, "max_count": None},
}
TTL_HOURS = {"1": 1, "24": 24, "168": 168, "720": 720, "never": None}

# 화면의 언어 목록 (값은 highlight.js 이름)
LANGUAGES = [
	("auto", "자동 감지"), ("plaintext", "그냥 글"), ("python", "Python"), ("c", "C"), ("cpp", "C++"), ("java", "Java"),
	("javascript", "JavaScript"), ("typescript", "TypeScript"), ("json", "JSON"), ("yaml", "YAML"), ("bash", "Shell"),
	("sql", "SQL"), ("go", "Go"), ("rust", "Rust"), ("kotlin", "Kotlin"), ("swift", "Swift"), ("csharp", "C#"),
	("php", "PHP"), ("matlab", "MATLAB"), ("r", "R"), ("xml", "HTML · XML"), ("css", "CSS"), ("markdown", "Markdown"),
	("latex", "LaTeX"), ("diff", "Diff · 패치"), ("ini", "INI · TOML"), ("dockerfile", "Dockerfile"), ("verilog", "Verilog"),
]
LANG_NAMES = dict(LANGUAGES)
EXT = {
	"plaintext": "txt", "python": "py", "c": "c", "cpp": "cpp", "java": "java", "javascript": "js", "typescript": "ts",
	"json": "json", "yaml": "yaml", "bash": "sh", "sql": "sql", "go": "go", "rust": "rs", "kotlin": "kt", "swift": "swift",
	"csharp": "cs", "php": "php", "matlab": "m", "r": "R", "xml": "html", "css": "css", "markdown": "md", "latex": "tex",
	"diff": "diff", "ini": "ini", "dockerfile": "Dockerfile", "verilog": "v",
}


def _limits(user):
	return PASTE_LIMITS.get(tier(user), PASTE_LIMITS["member"])


def _alive():
	now = timezone.now()
	return Paste.objects.exclude(expires_at__lte=now)


def _cleanup():
	Paste.objects.filter(expires_at__lte=timezone.now()).delete()


def _get_alive(paste_id):
	return _alive().filter(paste_id=paste_id).first()


def _gone(request):
	return render(request, "tools/link_gone.html", {"what": "붙여넣기"}, status=404)


@login_required
def paste_page(request):
	_cleanup()
	lim = _limits(request.user)
	fork = None
	if request.GET.get("fork"):
		src = _get_alive(request.GET["fork"])
		if src:
			fork = {"id": src.paste_id, "title": src.title, "language": src.language, "content": src.content}
	mine = Paste.objects.filter(owner=request.user)[:100]
	return render(request, "tools/paste.html", {
		"languages": LANGUAGES,
		"mine": mine,
		"fork": fork,
		"max_kb": lim["max_bytes"] // 1024,
		"max_count": lim["max_count"],
	})


@login_required
@require_POST
def paste_create(request):
	try:
		data = json.loads(request.body or b"{}")
	except ValueError:
		return JsonResponse({"error": "요청 형식이 올바르지 않아요."}, status=400)
	content = str(data.get("content") or "").replace("\r\n", "\n").replace("\x00", "")
	if not content.strip():
		return JsonResponse({"error": "붙여 넣을 내용이 비어 있어요."}, status=400)
	lim = _limits(request.user)
	size = len(content.encode("utf-8"))
	if size > lim["max_bytes"]:
		return JsonResponse({"error": f"한 번에 {lim['max_bytes'] // 1024:,}KB 까지 올릴 수 있어요. (지금 {size / 1024:,.0f}KB)"}, status=400)
	if lim["max_count"] is not None and _alive().filter(owner=request.user).count() >= lim["max_count"]:
		return JsonResponse({"error": f"붙여넣기는 {lim['max_count']}개까지 남겨 둘 수 있어요. 안 쓰는 걸 지워 주세요."}, status=400)
	language = str(data.get("language") or "auto")
	if language not in LANG_NAMES:
		language = "auto"
	ttl = str(data.get("ttl") or "168")
	hours = TTL_HOURS.get(ttl, 168)
	forked = str(data.get("forked_from") or "")[:24]
	paste = Paste.objects.create(
		owner=request.user,
		title=" ".join(str(data.get("title") or "").split())[:100],
		language=language,
		content=content,
		size=size,
		forked_from=forked if Paste.objects.filter(paste_id=forked).exists() else "",
		expires_at=timezone.now() + timedelta(hours=hours) if hours else None,
	)
	path = reverse("tools:paste_view", args=[paste.paste_id])
	return JsonResponse({"id": paste.paste_id, "path": path, "url": _absolute(request, path)})


def paste_view(request, paste_id):
	paste = _get_alive(paste_id)
	if not paste:
		return _gone(request)
	is_owner = request.user.is_authenticated and paste.owner_id == request.user.id
	if not is_owner:
		Paste.objects.filter(pk=paste.pk).update(view_count=F("view_count") + 1)
		paste.view_count += 1
	lines = paste.content.count("\n") + (0 if paste.content.endswith("\n") else 1)
	res = render(request, "tools/paste_view.html", {
		"paste": paste,
		"is_owner": is_owner,
		"can_delete": is_owner or request.user.is_superuser,
		"language_name": LANG_NAMES.get(paste.language, paste.language),
		"lines": lines,
		"share_url": _absolute(request, reverse("tools:paste_view", args=[paste.paste_id])),
	})
	res["X-Robots-Tag"] = "noindex"  # 링크를 아는 사람만 — 검색에는 안 나오게
	return res


def _filename(paste):
	base = re.sub(r"[^\w.\-가-힣]+", "_", paste.title).strip("._")[:60] or f"paste-{paste.paste_id}"
	ext = EXT.get(paste.language, "txt")
	if ext == "Dockerfile":
		return "Dockerfile"
	return base if base.lower().endswith("." + ext.lower()) else f"{base}.{ext}"


def paste_raw(request, paste_id):
	paste = _get_alive(paste_id)
	if not paste:
		return HttpResponse("없거나 만료된 붙여넣기예요.\n", status=404, content_type="text/plain; charset=utf-8")
	res = HttpResponse(paste.content, content_type="text/plain; charset=utf-8")
	res["X-Content-Type-Options"] = "nosniff"
	res["Content-Security-Policy"] = "sandbox; default-src 'none'"
	res["X-Robots-Tag"] = "noindex"
	if request.GET.get("download"):
		name = _filename(paste)
		res["Content-Disposition"] = f"attachment; filename=\"{name.encode('ascii', 'ignore').decode() or 'paste.txt'}\"; filename*=UTF-8''{quote(name)}"
	return res


@login_required
@require_POST
def paste_delete(request, paste_id):
	paste = get_object_or_404(Paste, paste_id=paste_id)
	if paste.owner_id != request.user.id and not request.user.is_superuser:
		return _gone(request)
	paste.delete()
	messages.success(request, "붙여넣기를 지웠어요.")
	return redirect("tools:paste")
