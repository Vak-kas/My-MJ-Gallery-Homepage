from django.core.management.base import BaseCommand

from tools.share_views import cleanup_expired


class Command(BaseCommand):
	help = "만료된 맡겨두기 파일과 오래 멈춘 미완성 업로드를 삭제합니다."

	def handle(self, *args, **options):
		self.stdout.write(f"{cleanup_expired()}개 삭제")
