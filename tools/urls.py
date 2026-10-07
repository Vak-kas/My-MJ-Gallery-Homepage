from django.urls import path

from . import speedtest, views

app_name = "tools"

urlpatterns = [
    path("", views.index, name="index"),
    path("duplex/", views.duplex, name="duplex"),
    path("subnet/", views.subnet, name="subnet"),
    path("speedtest/", views.speedtest, name="speedtest"),
    path("speedtest/ping/", speedtest.ping, name="speedtest_ping"),
    path("speedtest/download/", speedtest.download, name="speedtest_download"),
    path("speedtest/upload/", speedtest.upload, name="speedtest_upload"),
    path("stream/", views.stream_list, name="stream"),
    path("stream/<str:room_id>/", views.stream_room, name="stream_room"),
    path("stream/<str:room_id>/close/", views.stream_close, name="stream_close"),
    path("stream/<str:room_id>/join/", views.stream_join, name="stream_join"),
]
