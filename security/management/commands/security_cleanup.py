from django.core.management.base import BaseCommand

from security.utils import cleanup_old_records


class Command(BaseCommand):
    help = "90일 지난 로그인 기록과 작성자 IP 정보를 정리합니다."

    def handle(self, *args, **options):
        result = cleanup_old_records()
        self.stdout.write(self.style.SUCCESS(f"정리 완료: {result}"))
