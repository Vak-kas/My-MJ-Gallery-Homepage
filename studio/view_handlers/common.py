import json

from django.contrib.auth.decorators import user_passes_test
from django.http import JsonResponse
from django.db.models import F
from django.utils.dateparse import parse_date


def superuser_required(user):
    return user.is_authenticated and user.is_superuser


def admin_view(view_func):
    return user_passes_test(superuser_required, login_url="accounts:login")(view_func)


def parse_month_input(value):
    if not value:
        return None
    return parse_date(f"{value}-01")


def parse_gpa_input(request):
    score = request.POST.get("gpa_score", "").strip()
    scale = request.POST.get("gpa_scale", "").strip()
    fallback = request.POST.get("gpa", "").strip()

    if score and scale:
        return f"{score} / {scale}"
    if score:
        return score
    return fallback


def get_next_order(model_cls):
    model_cls.objects.all().update(order=F("order") + 1)
    return 0


def apply_reorder(model_cls, ordered_ids):
    if not ordered_ids:
        return False

    id_set = set(ordered_ids)
    if len(id_set) != len(ordered_ids):
        return False

    items = {item.id: item for item in model_cls.objects.filter(id__in=ordered_ids)}
    if len(items) != len(ordered_ids):
        return False

    updated = []
    for idx, item_id in enumerate(ordered_ids):
        item = items[item_id]
        item.order = idx
        updated.append(item)

    model_cls.objects.bulk_update(updated, ["order"])
    return True


def parse_reorder_payload(request):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None, JsonResponse({"ok": False, "message": "잘못된 요청입니다."}, status=400)

    ordered_ids = payload.get("ordered_ids", [])
    if not all(isinstance(v, int) for v in ordered_ids):
        return None, JsonResponse({"ok": False, "message": "ID 형식이 올바르지 않습니다."}, status=400)

    return ordered_ids, None
