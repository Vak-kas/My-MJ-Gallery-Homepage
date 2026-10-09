from .permissions import TIER_LABELS, tier


def user_tier(request):
	"""템플릿에서 {{ user_tier }} (anon·member·friend·admin) 와 {{ user_tier_label }} 로 회원 등급을 씀."""
	t = tier(getattr(request, "user", None))
	return {"user_tier": t, "user_tier_label": TIER_LABELS[t]}
