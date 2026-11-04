"""메일 설정 확인: venv/bin/python manage.py send_test_mail 받는주소@example.com

EMAIL_HOST 가 비어 있으면(MAIL_ENABLED=False) 실제로 보내지 않고 콘솔에만 찍힌다고 알려줌.
"""

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
	help = "테스트 메일을 한 통 보내 메일 설정이 되는지 확인"

	def add_arguments(self, parser):
		parser.add_argument("to")

	def handle(self, *args, **options):
		to = options["to"]
		if not settings.MAIL_ENABLED:
			self.stdout.write(self.style.WARNING("EMAIL_HOST 가 비어 있어요 — 실제로 보내지 않고 아래에 찍기만 해요 (.env 의 EMAIL_* 확인)"))
		sent = send_mail(
			"[MJ Gallery] 메일 설정 테스트",
			f"이 메일이 보이면 smjgallery.kr 서버가 메일을 보낼 수 있어요.\n보낸 시각: {timezone.localtime():%Y-%m-%d %H:%M:%S}\n"
			f"EMAIL_HOST={settings.EMAIL_HOST or '(없음)'} FROM={settings.DEFAULT_FROM_EMAIL}",
			None, [to], fail_silently=False,
		)
		self.stdout.write(self.style.SUCCESS(f"보냄: {sent}통 → {to}") if sent else self.style.ERROR("보내지 못했어요"))
