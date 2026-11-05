"""요청 본문 JSON 읽기 — 객체({...})가 아니면 ValueError.

json.loads 만 쓰면 본문이 [] 나 "문자열" 일 때 .get 에서 AttributeError 로 500 이 났음 (2026-11-05 점검).
기존 코드가 이미 ValueError 를 잡아 400 으로 돌려주므로 바꿔 끼우기만 하면 됨.
"""

import json


def loads_object(raw):
	data = json.loads(raw or b"{}")
	if not isinstance(data, dict):
		raise ValueError("JSON object required")
	return data
