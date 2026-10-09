from django.urls import path

from . import live_views, scores, views

app_name = "games"

urlpatterns = [
	path("", views.index, name="index"),
	path("ladder/", views.ladder, name="ladder"),
	path("roulette/", views.roulette, name="roulette"),
	path("seconds/", views.seconds, name="seconds"),
	path("reaction/", views.reaction, name="reaction"),
	path("bomb/", views.bomb, name="bomb"),
	path("updown/", views.updown, name="updown"),
	path("cards/", views.cards, name="cards"),
	path("2048/", views.g2048, name="2048"),
	path("2048/start/", scores.g2048_start, name="2048_start"),
	path("2048/submit/", scores.g2048_submit, name="2048_submit"),
	path("typing/", views.typing_page, name="typing"),
	path("typing/start/", scores.typing_start, name="typing_start"),
	path("typing/submit/", scores.typing_submit, name="typing_submit"),
	path("scores/<str:board>/", scores.board_view, name="scores"),
	path("omok/", live_views.omok_lobby, name="omok"),
	path("omok/new/", live_views.omok_create, name="omok_create"),
	path("omok/<str:room_id>/", live_views.omok_room, name="omok_room"),
	path("omok/<str:room_id>/close/", live_views.omok_close, name="omok_close"),
]
