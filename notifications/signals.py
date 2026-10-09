from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse

from blog.models import Comment, GuestbookEntry, Post

from .models import Notification
from .service import notify


def _by_admin(user):
    return bool(user and user.is_superuser)


def _skip(created, kwargs):
    # loaddata(raw=True) 로 옛 데이터를 옮길 때 알림·카톡이 다시 나가지 않게
    return not created or kwargs.get("raw")


@receiver(post_save, sender=Comment)
def comment_created(sender, instance, created, **kwargs):
    if _skip(created, kwargs) or _by_admin(instance.author):
        return
    post = instance.post
    notify(
        Notification.KIND_COMMENT,
        f"{instance.author_name} 님이 \"{post.title[:40]}\" 에 댓글을 남겼어요",
        instance.content[:120],
        reverse("blog:post_detail", args=[post.slug]) + "#comments",
    )


@receiver(post_save, sender=GuestbookEntry)
def guestbook_created(sender, instance, created, **kwargs):
    if _skip(created, kwargs) or _by_admin(instance.author):
        return
    notify(
        Notification.KIND_GUESTBOOK,
        f"{instance.author_name} 님이 방명록을 남겼어요",
        instance.message[:120],
        reverse("studio:community") + "?tab=guestbook",
    )


@receiver(post_save, sender=Post)
def post_published(sender, instance, created, **kwargs):
    # 다른 회원이 글을 발행했을 때만 (내 글·임시저장은 알리지 않음)
    if _skip(created, kwargs) or not instance.is_published or _by_admin(instance.author):
        return
    notify(
        Notification.KIND_POST,
        f"{instance.author.username if instance.author else '알 수 없음'} 님이 새 글을 올렸어요",
        instance.title[:120],
        reverse("blog:post_detail", args=[instance.slug]),
    )
