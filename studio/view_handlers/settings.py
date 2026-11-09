from django.contrib import messages
from django.shortcuts import redirect, render

from .. import site_settings
from .common import admin_view


@admin_view
def site_settings_view(request):
    current = site_settings.load()

    if request.method == "POST":
        nav_by_key = {i["key"]: i for i in current["nav"]}
        nav = []
        for key in request.POST.getlist("nav_order"):
            item = nav_by_key.get(key)
            if not item or item in nav:
                continue
            label = (request.POST.get(f"nav_label_{key}") or "").strip()[:20] or item["label"]
            state = request.POST.get(f"nav_state_{key}", "public")
            if item.get("fixed") or state not in dict(site_settings.NAV_STATES):
                state = "public"
            nav.append({**item, "label": label, "state": state})

        home_by_key = {s["key"]: s for s in current["home"]}
        home = []
        for key in request.POST.getlist("home_order"):
            section = home_by_key.get(key)
            if section and section not in home:
                home.append({**section, "enabled": request.POST.get(f"home_on_{key}") == "on"})

        if len(nav) != len(current["nav"]) or len(home) != len(current["home"]):
            messages.error(request, "설정이 올바르지 않습니다. 새로고침 후 다시 저장해 주세요.")
            return redirect("studio:settings")
        site_settings.save(nav, home)
        messages.success(request, "설정을 저장했어요. 사이트에 바로 반영돼요.")
        return redirect("studio:settings")

    return render(request, "studio/settings.html", {
        "nav_items": current["nav"],
        "nav_states": site_settings.NAV_STATES,
        "home_sections": current["home"],
    })
