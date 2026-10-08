from django.db.models import F
from django.shortcuts import render

from .utils import client_ip, matching_block


class IPBlockMiddleware:
    """차단 목록의 IP/대역에서 오는 요청은 403 안내 화면으로."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith(("/static/", "/media/")):
            block_id = matching_block(client_ip(request))
            if block_id:
                from .models import IPBlock
                IPBlock.objects.filter(pk=block_id).update(hit_count=F("hit_count") + 1)
                return render(request, "security/blocked.html", status=403)
        return self.get_response(request)
