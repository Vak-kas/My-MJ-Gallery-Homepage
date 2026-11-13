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
	path("api/draft/", views.api_draft, name="api_draft"),
	path("api/labels/", views.api_labels, name="api_labels"),
	path("api/prefs/", views.api_prefs, name="api_prefs"),
	path("api/contacts/", views.api_contacts, name="api_contacts"),
	path("api/app-passwords/", views.api_app_passwords, name="api_app_passwords"),
	path("api/schedule/", views.api_schedule, name="api_schedule"),
	path("api/diagnose/", views.api_diagnose, name="api_diagnose"),
	path("api/dmarc/", views.api_dmarc, name="api_dmarc"),
	path("attachment/", views.attachment, name="attachment"),
	path("raw/", views.raw, name="raw"),
]
