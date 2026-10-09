from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from blog.models import Post
from studio import site_settings


def _open(key):
	return site_settings.nav_state(key) == "public"


class StaticSitemap(Sitemap):
	protocol = "https"
	changefreq = "weekly"

	def items(self):
		names = ["main:home"]
		if _open("blog"):
			names += ["blog:index", "blog:tech", "blog:board", "blog:life"]
		if _open("photo"):
			names.append("main:photos")
		if _open("tool"):
			from tools.registry import TOOLS
			names.append("tools:index")
			names += [t["url_name"] for t in TOOLS if t.get("access") == "public"]
		return names

	def location(self, item):
		return reverse(item)

	def priority(self, item):
		return 1.0 if item == "main:home" else 0.6


class PostSitemap(Sitemap):
	protocol = "https"
	changefreq = "monthly"
	priority = 0.8

	def items(self):
		if not _open("blog"):
			return Post.objects.none()
		return (Post.objects.filter(is_published=True, visibility=Post.VISIBILITY_PUBLIC)
				.exclude(category=Post.CATEGORY_SECRET).order_by("-published_at"))

	def location(self, post):
		return reverse("blog:post_detail", args=[post.slug])

	def lastmod(self, post):
		return post.updated_at
