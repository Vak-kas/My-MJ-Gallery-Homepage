from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from studio.view_handlers.common import admin_view

from .models import Notification


@admin_view
def notification_list(request):
    qs = Notification.objects.all()
    kind = (request.GET.get("kind") or "").strip()
    if kind in dict(Notification.KIND_CHOICES):
        qs = qs.filter(kind=kind)
    else:
        kind = ""
    page_obj = Paginator(qs, 40).get_page(request.GET.get("page"))
    return render(request, "notifications/list.html", {
        "page_obj": page_obj,
        "items": list(page_obj.object_list),
        "kind": kind,
        "kinds": Notification.KIND_CHOICES,
        "unread_total": Notification.objects.filter(is_read=False).count(),
    })


@admin_view
@require_POST
def notification_open(request, id):
    item = get_object_or_404(Notification, id=id)
    if not item.is_read:
        item.is_read = True
        item.save(update_fields=["is_read"])
    if item.url and url_has_allowed_host_and_scheme(item.url, allowed_hosts={request.get_host()}):
        return redirect(item.url)
    return redirect("notifications:list")


@admin_view
@require_POST
def notification_read_all(request):
    Notification.objects.filter(is_read=False).update(is_read=True)
    return redirect("notifications:list")


@admin_view
@require_POST
def notification_clear_read(request):
    Notification.objects.filter(is_read=True).delete()
    return redirect("notifications:list")
