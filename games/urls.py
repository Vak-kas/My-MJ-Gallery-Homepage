from django.urls import path

from . import views

app_name = "games"

urlpatterns = [
	path("", views.index, name="index"),
	path("ladder/", views.ladder, name="ladder"),
	path("roulette/", views.roulette, name="roulette"),
]
