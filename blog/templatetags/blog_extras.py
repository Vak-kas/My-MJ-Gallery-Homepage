import json

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


def _render_list_items(items, style):
    parts = []
    list_cls = "list-decimal" if style == "ordered" else "list-disc"
    for item in items:
        if isinstance(item, dict):
            text = item.get("content", "")
            sub = item.get("items", [])
            sub_html = ""
            if sub:
                sub_tag = "ol" if style == "ordered" else "ul"
                sub_html = f'<{sub_tag} class="{list_cls} pl-5 mt-1">{_render_list_items(sub, style)}</{sub_tag}>'
            parts.append(f"<li class='mb-1'>{text}{sub_html}</li>")
        else:
            parts.append(f"<li class='mb-1'>{item}</li>")
    return "".join(parts)


@register.filter
def render_editorjs(content):
    """Editor.js JSON → HTML 렌더링. 일반 텍스트면 단락으로 폴백."""
    if not content:
        return mark_safe("")
    try:
        data = json.loads(content)
        blocks = data.get("blocks", [])
    except (json.JSONDecodeError, TypeError, ValueError):
        return mark_safe(f'<p class="mb-4 leading-relaxed">{escape(content)}</p>')

    html = []
    for block in blocks:
        t = block.get("type", "paragraph")
        d = block.get("data", {})

        if t == "paragraph":
            text = d.get("text", "")
            align = d.get("alignment", "left")
            a_cls = f"text-{align}" if align in ("left", "center", "right", "justify") else ""
            html.append(f'<p class="mb-4 leading-[1.85] {a_cls}">{text}</p>')

        elif t == "header":
            text = d.get("text", "")
            level = max(1, min(6, int(d.get("level", 2))))
            sizes = {
                1: "text-[2rem] font-bold mt-10 mb-4 tracking-tight",
                2: "text-[1.5rem] font-semibold mt-8 mb-3 tracking-tight",
                3: "text-[1.25rem] font-semibold mt-6 mb-2",
                4: "text-[1.1rem] font-semibold mt-5 mb-2",
                5: "text-[1rem] font-semibold mt-4 mb-1",
                6: "text-[0.9rem] font-semibold mt-3 mb-1 text-[#6e6e73]",
            }
            cls = sizes.get(level, sizes[2])
            html.append(f'<h{level} class="{cls}">{text}</h{level}>')

        elif t in ("list", "nestedList"):
            style = d.get("style", "unordered")
            items = d.get("items", [])
            tag = "ol" if style == "ordered" else "ul"
            list_cls = "list-decimal" if style == "ordered" else "list-disc"
            inner = _render_list_items(items, style)
            html.append(f'<{tag} class="{list_cls} pl-6 mb-4 space-y-0.5">{inner}</{tag}>')

        elif t == "checklist":
            rows = []
            for item in d.get("items", []):
                checked = item.get("checked", False)
                text = item.get("text", "")
                icon = "✅" if checked else "⬜"
                strike = "line-through text-[#aeaeb2]" if checked else ""
                rows.append(
                    f'<li class="flex items-start gap-2 mb-1.5">'
                    f'<span class="flex-shrink-0 mt-0.5">{icon}</span>'
                    f'<span class="{strike}">{text}</span></li>'
                )
            html.append(f'<ul class="mb-4 space-y-0.5">{"".join(rows)}</ul>')

        elif t == "quote":
            text = d.get("text", "")
            caption = d.get("caption", "")
            cap = f'<footer class="mt-2 text-sm not-italic text-[#8e8e93]">— {caption}</footer>' if caption else ""
            html.append(
                f'<blockquote class="border-l-4 border-[#d2d2d7] pl-5 py-1 italic text-[#6e6e73] my-5">'
                f'{text}{cap}</blockquote>'
            )

        elif t == "code":
            code = escape(d.get("code", ""))
            html.append(
                f'<pre class="bg-[#f2f2f7] rounded-xl p-4 mb-4 overflow-x-auto text-[0.85rem] '
                f'font-mono leading-relaxed text-[#1d1d1f]"><code>{code}</code></pre>'
            )

        elif t == "delimiter":
            html.append(
                '<div class="my-10 flex items-center justify-center gap-4 text-[#c7c7cc] text-lg select-none">'
                '<span>✦</span><span>✦</span><span>✦</span></div>'
            )

        elif t == "warning":
            title = d.get("title", "알림")
            message = d.get("message", "")
            html.append(
                f'<div class="bg-amber-50 border border-amber-200 rounded-xl p-4 mb-4">'
                f'<p class="font-semibold text-amber-800 mb-1">⚠️ {title}</p>'
                f'<p class="text-amber-700 text-sm leading-relaxed">{message}</p></div>'
            )

        elif t == "table":
            rows_data = d.get("content", [])
            with_headings = d.get("withHeadings", False)
            if rows_data:
                rows_html = []
                for i, row in enumerate(rows_data):
                    cells = []
                    for cell in row:
                        if i == 0 and with_headings:
                            cells.append(
                                f'<th class="border border-[#e5e5ea] px-3 py-2 bg-[#f9f9fb] '
                                f'font-semibold text-left text-sm">{cell}</th>'
                            )
                        else:
                            cells.append(f'<td class="border border-[#e5e5ea] px-3 py-2 text-sm">{cell}</td>')
                    rows_html.append(f'<tr>{"".join(cells)}</tr>')
                html.append(
                    f'<div class="overflow-x-auto mb-4">'
                    f'<table class="w-full border-collapse">{"".join(rows_html)}</table></div>'
                )

        elif t == "toggle":
            title = d.get("title", "")
            items = d.get("items", [])
            inner = "".join(f"<p class='mb-1'>{item}</p>" for item in items)
            html.append(
                f'<details class="mb-3 border border-[#e5e5ea] rounded-xl group">'
                f'<summary class="cursor-pointer select-none px-4 py-3 font-medium '
                f'hover:bg-[#f9f9fb] rounded-xl list-none flex items-center gap-2">'
                f'<span class="transition-transform group-open:rotate-90 text-[#aeaeb2]">▶</span>'
                f'{title}</summary>'
                f'<div class="px-4 pb-4 pt-2 text-[#6e6e73] text-sm leading-relaxed">{inner}</div>'
                f'</details>'
            )

    return mark_safe("".join(html))
