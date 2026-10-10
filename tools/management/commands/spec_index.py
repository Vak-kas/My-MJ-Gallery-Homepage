"""3GPP 본문 검색용 규격 받기·나누기.

  python manage.py spec_index --pending        기다리는 것 모두 (화면의 관리자 버튼이 부름)
  python manage.py spec_index --default        기본 규격(NR 주요·NTN)을 넣고 받기
  python manage.py spec_index 38.331 38.321    이 번호들을 넣고 받기
"""

from django.core.management.base import BaseCommand

from tools import specdocs


class Command(BaseCommand):
	help = "3GPP 규격 최신판을 받아 절 단위로 나눠 본문 검색에 넣는다"

	def add_arguments(self, parser):
		parser.add_argument("numbers", nargs="*")
		parser.add_argument("--pending", action="store_true")
		parser.add_argument("--default", action="store_true")

	def handle(self, numbers, pending, default, **options):
		if default:
			specdocs.queue(specdocs.DEFAULT_SPECS)
		if numbers:
			specdocs.queue(numbers)
		n = specdocs.run_pending()
		self.stdout.write(f"{n}개 처리했어요." if n else "처리할 게 없거나 다른 프로세스가 받는 중이에요.")
