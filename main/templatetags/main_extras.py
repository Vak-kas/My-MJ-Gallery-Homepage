from urllib.parse import unquote

from django import template

register = template.Library()


@register.filter
def urldecode(value):
	"""퍼센트 인코딩된 주소를 사람이 읽게 (예: 한글 위키 주소). 깨진 바이트는 그대로."""
	try:
		return unquote(str(value), errors="replace")
	except Exception:  # noqa: BLE001
		return value
