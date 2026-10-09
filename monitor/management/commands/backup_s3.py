"""S3 백업 실행·목록·내려받기.

  manage.py backup_s3                 지금 백업 (run_scheduled 가 하루 한 번 자동 실행)
  manage.py backup_s3 --list          버킷에 있는 DB 백업 목록
  manage.py backup_s3 --download DIR  가장 최근 DB + media/ + private_media/ 를 DIR 로 내려받기
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.template.defaultfilters import filesizeformat

from monitor import backup


class Command(BaseCommand):
    help = "DB·업로드 파일을 S3 에 백업 / 목록 / 내려받기"

    def add_arguments(self, parser):
        parser.add_argument("--list", action="store_true", help="DB 백업 목록")
        parser.add_argument("--download", metavar="DIR", help="최근 DB 와 파일 전체를 DIR 로 내려받기")

    def handle(self, *args, **options):
        if not backup.configured():
            raise CommandError(".env 에 BACKUP_S3_BUCKET, BACKUP_AWS_ACCESS_KEY_ID, BACKUP_AWS_SECRET_ACCESS_KEY 를 넣어 주세요.")
        if options["list"]:
            return self.list_db()
        if options["download"]:
            return self.download(Path(options["download"]).expanduser())
        try:
            r = backup.run()
        except Exception as e:
            raise CommandError(f"백업 실패: {e}")
        self.stdout.write(self.style.SUCCESS(
            f"백업 완료 ({r['seconds']}초): {r['db_key']} {filesizeformat(r['db_size'])}, "
            f"파일 {r['uploaded']}개 새로 올림({filesizeformat(r['bytes'])}), {r['skipped']}개 그대로, 오래된 DB {r['pruned']}개 정리"
        ))

    def list_db(self):
        s3 = backup.client()
        objs = []
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=settings.BACKUP_S3_BUCKET, Prefix="db/"):
            objs += page.get("Contents", [])
        for o in sorted(objs, key=lambda o: o["Key"]):
            self.stdout.write(f"{o['Key']}  {filesizeformat(o['Size'])}")
        self.stdout.write(f"DB 백업 {len(objs)}개")

    def download(self, dest):
        s3 = backup.client()
        bucket = settings.BACKUP_S3_BUCKET
        count = 0
        latest = max(backup.remote_sizes(s3, "db"), default=None)
        if latest:
            (dest / "db").mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, latest, str(dest / latest))
            self.stdout.write(f"DB: {dest / latest}")
            count += 1
        for prefix, _ in backup.DIRS:
            for key, size in backup.remote_sizes(s3, prefix).items():
                target = dest / key
                if target.exists() and target.stat().st_size == size:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                s3.download_file(bucket, key, str(target))
                count += 1
        self.stdout.write(self.style.SUCCESS(f"{dest} 에 {count}개 내려받음"))
