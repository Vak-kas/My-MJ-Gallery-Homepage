"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path

from django.contrib.sitemaps.views import sitemap

from blog.feeds import LatestPostsFeed
from main.sitemaps import PostSitemap, StaticSitemap
from main import pwa
from main.views import og_card, robots_txt
from tools.link_views import short_redirect
from tools.webhook_views import hook_receive
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('blog/feed/', LatestPostsFeed(), name='blog_feed'),
    path('blog/', include(('blog.urls', 'blog'), namespace='blog')),
    path('tools/', include(('tools.urls', 'tools'), namespace='tools')),
    path('games/', include(('games.urls', 'games'), namespace='games')),
    path('s/<str:code>', short_redirect, name='short_redirect'),
    # 웹훅 확인기: 끝에 / 가 없어도, 뒤에 아무 경로가 붙어도 받음 (POST 를 / 붙은 주소로 옮기면 본문이 사라져서)
    re_path(r'^hook/(?P<bin_id>[\w-]{8,32})(?P<rest>/.*)?$', hook_receive, name='hook_receive'),
    path('sitemap.xml', sitemap, {'sitemaps': {'pages': StaticSitemap, 'posts': PostSitemap}}, name='sitemap'),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('manifest.webmanifest', pwa.manifest, name='pwa_manifest'),
    path('sw.js', pwa.service_worker, name='pwa_sw'),
    path('offline/', pwa.offline, name='pwa_offline'),
    path('app/', pwa.install, name='pwa_install'),
    path('og/<str:kind>/<str:key>.png', og_card, name='og_card'),
    path('', include('main.urls')),
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('studio/', include('studio.urls')),
    path('notifications/', include('notifications.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
    if not getattr(settings, "USE_S3", False):
        urlpatterns += static(
            settings.MEDIA_URL,
            document_root=settings.MEDIA_ROOT
        )