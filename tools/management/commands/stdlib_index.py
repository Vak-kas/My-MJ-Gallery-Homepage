from django.core.management.base import BaseCommand

from tools.stdlib import index_doc


class Command(BaseCommand):
	help = "표준 서재 문서 하나를 절 단위로 나눠 저장 (업로드 뒤 따로 뜬 프로세스로 실행)"

	def add_arguments(self, parser):
		parser.add_argument("doc_id", type=int)

	def handle(self, doc_id, **options):
		index_doc(doc_id)
