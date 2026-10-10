"""3GPP 규격 목록을 지금 새로 받기: python manage.py specs_refresh"""

from django.core.management.base import BaseCommand, CommandError

from tools import specs


class Command(BaseCommand):
	help = "3GPP 규격 현황표를 받아 TS/TR 찾기 목록을 새로 만든다"

	def handle(self, *args, **options):
		if not specs.refresh_index():
			raise CommandError("3GPP 현황표를 받지 못했어요.")
		data = specs.load_index()
		self.stdout.write(f"규격 {len(data['specs']):,}개 ({data['fetched']})")
