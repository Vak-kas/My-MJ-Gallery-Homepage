from django.contrib.syndication.views import Feed
from django.urls import reverse
from django.utils.feedgenerator import Rss201rev2Feed

from main.seo import DEFAULT_DESCRIPTION, post_meta
from studio import site_settings

from .models import Post


class LatestPostsFeed(Feed):
	"""블로그 RSS (공개·발행된 글 최신 20개)."""

	feed_type = Rss201rev2Feed
	title = "서민재 갤러리 블로그"
	description = DEFAULT_DESCRIPTION

	def link(self):
		return reverse("blog:index")

	def items(self):
		if site_settings.nav_state("blog") != "public":
			return []
		return (Post.objects.filter(is_published=True, visibility=Post.VISIBILITY_PUBLIC)
				.exclude(category=Post.CATEGORY_SECRET).select_related("author").prefetch_related("tags")
				.order_by("-published_at")[:20])

	def item_title(self, post):
		return post.title

	def item_description(self, post):
		return post_meta(post)["description"]

	def item_link(self, post):
		return reverse("blog:post_detail", args=[post.slug])

	def item_pubdate(self, post):
		return post.published_at

	def item_categories(self, post):
		return [t.name for t in post.tags.all()]
