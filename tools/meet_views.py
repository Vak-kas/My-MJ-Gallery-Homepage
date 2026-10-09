"""팀플 일정 맞추기 (만들기는 회원, 링크를 받은 사람은 로그인 없이 참여)."""

import hashlib
import json
import secrets
from datetime import date, datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from main import og_cards, seo
from security.utils import client_ip

from .link_views import _absolute
from .models import Meeting, MeetingResponse

MAX_DATES = 31
MAX_ACTIVE_MEETINGS = 30
MAX_RESPONSES = 60
KEEP_DAYS_AFTER = 14  # 마지막 날짜가 지나고 이만큼 뒤에 지움
SLOT_CHOICES = (15, 30, 60)
JOIN_LIMIT = (30, 10 * 60)  # IP 하나가 10분에 이름 등록 30번까지


def _hash(key):
	return hashlib.sha256(key.encode()).hexdigest()


def _get(meet_id):
	meeting = Meeting.objects.filter(meet_id=meet_id, expires_at__gt=timezone.now()).first()
	if not meeting:
		raise Http404("일정이 없거나 기간이 지나 지워졌어요.")
	return meeting


def _body(request):
	try:
		return json.loads(request.body or b"{}")
	except ValueError:
		return {}


def _err(msg, status=400):
	return JsonResponse({"ok": False, "error": msg}, status=status)


def _parse_form(post):
	title = (post.get("title") or "").strip()[:80]
	if not title:
		raise ValueError("일정 이름을 적어 주세요.")
	raw_dates = [d for d in (post.get("dates") or "").split(",") if d]
	try:
		dates = sorted({date.fromisoformat(d) for d in raw_dates})
	except ValueError:
		raise ValueError("날짜 형식이 올바르지 않아요.")
	if not dates:
		raise ValueError("날짜를 하루 이상 골라 주세요.")
	if len(dates) > MAX_DATES:
		raise ValueError(f"날짜는 {MAX_DATES}일까지 고를 수 있어요.")
	today = timezone.localdate()
	if dates[-1] < today - timedelta(days=1) or dates[0] > today + timedelta(days=366):
		raise ValueError("지났거나 1년 넘게 남은 날짜예요.")
	try:
		start, end, slot = int(post.get("start", 540)), int(post.get("end", 1320)), int(post.get("slot", 30))
	except ValueError:
		raise ValueError("시간을 다시 골라 주세요.")
	if slot not in SLOT_CHOICES or not (0 <= start < end <= 1440) or start % slot or end % slot:
		raise ValueError("시간 범위를 다시 골라 주세요.")
	return {
		"title": title,
		"note": (post.get("note") or "").strip()[:300],
		"dates": [d.isoformat() for d in dates],
		"start_min": start,
		"end_min": end,
		"slot_min": slot,
		"expires_at": timezone.make_aware(datetime.combine(dates[-1] + timedelta(days=KEEP_DAYS_AFTER + 1), time.min)),
	}


@login_required
def meet(request):
	mine = Meeting.objects.filter(owner=request.user, expires_at__gt=timezone.now())
	if request.method == "POST":
		try:
			if mine.count() >= MAX_ACTIVE_MEETINGS:
				raise ValueError(f"일정은 {MAX_ACTIVE_MEETINGS}개까지 둘 수 있어요. 끝난 일정을 지워 주세요.")
			fields = _parse_form(request.POST)
		except ValueError as exc:
			messages.error(request, str(exc))
			return redirect("tools:meet")
		meeting = Meeting.objects.create(owner=request.user, **fields)
		return redirect("tools:meet_room", meet_id=meeting.meet_id)
	rows = [{"obj": m, "url": _absolute(request, m.get_absolute_url()), "count": m.responses.count()} for m in mine]
	return render(request, "tools/meet.html", {"rows": rows, "slot_choices": SLOT_CHOICES, "max_dates": MAX_DATES})


@ensure_csrf_cookie
def meet_room(request, meet_id):
	meeting = _get(meet_id)
	return render(request, "tools/meet_room.html", {
		"meeting": meeting,
		"share_url": _absolute(request, meeting.get_absolute_url()),
		"is_owner": request.user.is_authenticated and request.user.id == meeting.owner_id,
		"meta": seo.build(
			f"📅 {meeting.title}",
			f"{_date_range(meeting)} · {meeting.start_min // 60}시~{meeting.end_min // 60}시 중 되는 시간을 칠해 주세요. 로그인 없이 이름만 넣으면 돼요.",
			og_cards.image_url("tool", "meet"),
			path=request.path,
		),
	})


def _date_range(meeting):
	first, last = date.fromisoformat(meeting.dates[0]), date.fromisoformat(meeting.dates[-1])
	text = f"{first.month}/{first.day}"
	if last != first:
		text += f" ~ {last.month}/{last.day}"
	return text + (f" ({len(meeting.dates)}일)" if len(meeting.dates) > 1 else "")


def _state(meeting):
	return {
		"ok": True,
		"version": meeting.updated_at.isoformat(),
		"title": meeting.title,
		"dates": meeting.dates,
		"start": meeting.start_min,
		"end": meeting.end_min,
		"slot": meeting.slot_min,
		"responses": [{"id": r.id, "name": r.name, "slots": r.slots} for r in meeting.responses.all()],
	}


@require_GET
def meet_state(request, meet_id):
	meeting = _get(meet_id)
	if request.GET.get("v") == meeting.updated_at.isoformat():
		return JsonResponse({"ok": True, "same": True})
	return JsonResponse(_state(meeting))


def _touch(meeting):
	Meeting.objects.filter(pk=meeting.pk).update(updated_at=timezone.now())


@require_POST
def meet_join(request, meet_id):
	"""이름으로 들어오기. 처음이면 만들고, 이미 있는 이름이면 이 기기의 열쇠나 비밀번호가 맞아야 함."""
	meeting = _get(meet_id)
	data = _body(request)
	name = " ".join(str(data.get("name") or "").split())[:30]
	pin = str(data.get("pin") or "")[:64]
	key = str(data.get("key") or "")
	if not name:
		return _err("이름을 적어 주세요.")
	existing = meeting.responses.filter(name=name).first()
	if existing:
		if key and secrets.compare_digest(existing.key_hash, _hash(key)):
			return JsonResponse({"ok": True, "id": existing.id, "name": existing.name, "key": key, "slots": existing.slots})
		if existing.pin_hash and pin and check_password(pin, existing.pin_hash):
			new_key = secrets.token_urlsafe(24)
			existing.key_hash = _hash(new_key)
			existing.save(update_fields=["key_hash"])
			return JsonResponse({"ok": True, "id": existing.id, "name": existing.name, "key": new_key, "slots": existing.slots})
		if existing.pin_hash:
			return _err("이미 있는 이름이에요. 그 이름으로 정한 비밀번호를 넣어 주세요.", 403)
		return _err("이미 있는 이름이에요. 다른 이름을 쓰거나, 처음 들어온 기기에서 고쳐 주세요.", 403)

	ip_key = f"meet:join:{client_ip(request)}"
	cache.add(ip_key, 0, JOIN_LIMIT[1])
	if cache.incr(ip_key) > JOIN_LIMIT[0]:
		return _err("잠시 뒤 다시 시도해 주세요.", 429)
	if meeting.responses.count() >= MAX_RESPONSES:
		return _err(f"한 일정에는 {MAX_RESPONSES}명까지 참여할 수 있어요.", 403)
	new_key = secrets.token_urlsafe(24)
	try:
		with transaction.atomic():
			resp = MeetingResponse.objects.create(meeting=meeting, name=name, key_hash=_hash(new_key), pin_hash=make_password(pin) if pin else "")
	except IntegrityError:
		return _err("방금 같은 이름이 들어왔어요. 다른 이름을 써 주세요.", 409)
	_touch(meeting)
	return JsonResponse({"ok": True, "id": resp.id, "name": resp.name, "key": new_key, "slots": []})


def _response_for(meeting, key):
	if not key:
		return None
	return meeting.responses.filter(key_hash=_hash(key)).first()


@require_POST
def meet_save(request, meet_id):
	meeting = _get(meet_id)
	data = _body(request)
	resp = _response_for(meeting, str(data.get("key") or ""))
	if not resp:
		return _err("이 기기에서 다시 이름을 넣어 주세요.", 403)
	total = meeting.slot_count
	try:
		slots = sorted({int(s) for s in data.get("slots") or [] if 0 <= int(s) < total})
	except (TypeError, ValueError):
		return _err("칸 정보가 올바르지 않아요.")
	resp.slots = slots
	resp.save(update_fields=["slots", "updated_at"])
	_touch(meeting)
	return JsonResponse({"ok": True, "count": len(slots)})


@require_POST
def meet_remove(request, meet_id):
	"""참여자 빼기: 본인(열쇠) 또는 만든 사람."""
	meeting = _get(meet_id)
	data = _body(request)
	is_owner = request.user.is_authenticated and request.user.id == meeting.owner_id
	if is_owner and data.get("id"):
		resp = meeting.responses.filter(pk=data.get("id")).first()
	else:
		resp = _response_for(meeting, str(data.get("key") or ""))
	if not resp:
		return _err("뺄 수 없어요.", 403)
	resp.delete()
	_touch(meeting)
	return JsonResponse({"ok": True})


@login_required
@require_POST
def meet_delete(request, meet_id):
	meeting = get_object_or_404(Meeting, meet_id=meet_id, owner=request.user)
	meeting.delete()
	messages.success(request, f"'{meeting.title}' 일정을 지웠어요.")
	return redirect("tools:meet")


def cleanup_expired():
	return Meeting.objects.filter(expires_at__lte=timezone.now()).delete()[0]
