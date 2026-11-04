from django.urls import path

from . import views

app_name = "webmail"

urlpatterns = [
	path("", views.index, name="index"),
	path("api/state/", views.api_state, name="api_state"),
	path("api/unread/", views.api_unread, name="api_unread"),
	path("api/list/", views.api_list, name="api_list"),
	path("api/message/", views.api_message, name="api_message"),
	path("api/action/", views.api_action, name="api_action"),
	path("api/send/", views.api_send, name="api_send"),
	path("attachment/", views.attachment, name="attachment"),
]
