from django.urls import path

from . import clipboard_views, speedtest, views

app_name = "tools"

urlpatterns = [
    path("", views.index, name="index"),
    path("duplex/", views.duplex, name="duplex"),
    path("subnet/", views.subnet, name="subnet"),
    path("speedtest/", views.speedtest, name="speedtest"),
    path("speedtest/ping/", speedtest.ping, name="speedtest_ping"),
    path("speedtest/download/", speedtest.download, name="speedtest_download"),
    path("speedtest/upload/", speedtest.upload, name="speedtest_upload"),
    path("clipboard/", clipboard_views.clipboard_page, name="clipboard"),
    path("clipboard/api/items/", clipboard_views.clipboard_list, name="clipboard_list"),
    path("clipboard/api/items/add/", clipboard_views.clipboard_add, name="clipboard_add"),
    path("clipboard/api/items/clear/", clipboard_views.clipboard_clear, name="clipboard_clear"),
    path("clipboard/api/items/<int:item_id>/pin/", clipboard_views.clipboard_pin, name="clipboard_pin"),
    path("clipboard/api/items/<int:item_id>/delete/", clipboard_views.clipboard_delete, name="clipboard_delete"),
    path("clipboard/<int:item_id>/file/", clipboard_views.clipboard_file, name="clipboard_file"),
    path("stream/", views.stream_list, name="stream"),
    path("stream/<str:room_id>/", views.stream_room, name="stream_room"),
    path("stream/<str:room_id>/close/", views.stream_close, name="stream_close"),
    path("stream/<str:room_id>/join/", views.stream_join, name="stream_join"),
]
