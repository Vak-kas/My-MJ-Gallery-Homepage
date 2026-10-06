import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

from blog.models import GuestbookEntry


class Command(BaseCommand):
	help = "방명록을 JSON 으로 백업한 뒤 전부 삭제합니다. --yes 없이 실행하면 개수만 보여줍니다."

	def add_arguments(self, parser):
		parser.add_argument("--yes", action="store_true", help="실제로 삭제합니다.")
		parser.add_argument(
			"--backup-dir",
			default=str(Path(settings.BASE_DIR) / "backups"),
			help="백업 파일을 저장할 폴더 (기본: 프로젝트/backups)",
		)

	def handle(self, *args, **options):
		entries = list(GuestbookEntry.objects.order_by("id").values())
		self.stdout.write(f"방명록 {len(entries)}개")
		if not entries:
			return
		if not options["yes"]:
			self.stdout.write("미리보기만 했습니다. 삭제하려면 --yes 를 붙여 다시 실행하세요.")
			for entry in entries[:5]:
				self.stdout.write(f"  #{entry['id']} {entry['author_name'][:20]!r}: {entry['message'][:40]!r}")
			return

		backup_dir = Path(options["backup_dir"])
		backup_dir.mkdir(parents=True, exist_ok=True)
		backup_path = backup_dir / f"guestbook-{timezone.now():%Y%m%d-%H%M%S}.json"
		backup_path.write_text(json.dumps(entries, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2), encoding="utf-8")
		self.stdout.write(f"백업: {backup_path}")

		deleted, _ = GuestbookEntry.objects.all().delete()
		self.stdout.write(self.style.SUCCESS(f"방명록 {deleted}개를 삭제했습니다."))
