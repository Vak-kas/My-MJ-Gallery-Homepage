"""S3 백업: DB 를 압축해 날짜별로 올리고, media/·private_media/ 는 바뀐 파일만 올림.

버킷 구조
  db/2026-10-09_0400.sqlite3.gz   (PostgreSQL 이면 .pgdump, BACKUP_KEEP_DAYS 지나면 지움)
  media/<원래 경로>
  private_media/<원래 경로>
"""

import gzip
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

STATUS_KEY = "monitor:backup:status"
RUNNING_KEY = "monitor:backup:running"
DIRS = (("media", "MEDIA_ROOT"), ("private_media", "PRIVATE_MEDIA_ROOT"))


def configured():
    return bool(settings.BACKUP_S3_BUCKET and settings.BACKUP_AWS_ACCESS_KEY_ID and settings.BACKUP_AWS_SECRET_ACCESS_KEY)


def client():
    import boto3

    return boto3.client(
        "s3",
        region_name=settings.BACKUP_S3_REGION,
        aws_access_key_id=settings.BACKUP_AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.BACKUP_AWS_SECRET_ACCESS_KEY,
    )


def status():
    return cache.get(STATUS_KEY)


def is_running():
    return bool(cache.get(RUNNING_KEY))


def dump_db(workdir):
    """DB 를 일관된 상태로 복사해 파일 경로와 S3 키 이름을 돌려줌."""
    db = settings.DATABASES["default"]
    stamp = timezone.localtime().strftime("%Y-%m-%d_%H%M")
    if db["ENGINE"].endswith("sqlite3"):
        raw = Path(workdir) / "db.sqlite3"
        src = sqlite3.connect(str(db["NAME"]))
        dst = sqlite3.connect(str(raw))
        try:
            src.backup(dst)  # 쓰는 중이어도 안전한 온라인 복사
        finally:
            dst.close()
            src.close()
        out = Path(workdir) / "db.sqlite3.gz"
        with open(raw, "rb") as f, gzip.open(out, "wb", compresslevel=6) as g:
            shutil.copyfileobj(f, g)
        raw.unlink()
        return out, f"db/{stamp}.sqlite3.gz"
    if "postgresql" in db["ENGINE"]:
        out = Path(workdir) / "db.pgdump"
        env = {**os.environ, "PGPASSWORD": db.get("PASSWORD") or ""}
        subprocess.run(
            ["pg_dump", "-Fc", "-h", db.get("HOST") or "localhost", "-p", str(db.get("PORT") or 5432),
             "-U", db["USER"], "-f", str(out), db["NAME"]],
            check=True, env=env, capture_output=True, timeout=30 * 60,
        )
        return out, f"db/{stamp}.pgdump"
    raise RuntimeError(f"지원하지 않는 DB: {db['ENGINE']}")


def remote_sizes(s3, prefix):
    sizes = {}
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=settings.BACKUP_S3_BUCKET, Prefix=prefix + "/"):
        for obj in page.get("Contents", []):
            sizes[obj["Key"]] = obj["Size"]
    return sizes


def sync_dir(s3, root, prefix):
    """root 아래 파일 중 버킷에 없거나 크기가 다른 것만 올림. 서버에서 지운 파일은 버킷에 그대로 둠."""
    root = Path(root)
    if not root.is_dir():
        return 0, 0, 0
    have = remote_sizes(s3, prefix)
    uploaded = skipped = nbytes = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        key = f"{prefix}/{path.relative_to(root).as_posix()}"
        size = path.stat().st_size
        if have.get(key) == size:
            skipped += 1
            continue
        s3.upload_file(str(path), settings.BACKUP_S3_BUCKET, key)
        uploaded += 1
        nbytes += size
    return uploaded, skipped, nbytes


def prune_db(s3, keep_days):
    cutoff = timezone.now() - timedelta(days=keep_days)
    old = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=settings.BACKUP_S3_BUCKET, Prefix="db/"):
        old += [{"Key": o["Key"]} for o in page.get("Contents", []) if o["LastModified"] < cutoff]
    for i in range(0, len(old), 1000):
        s3.delete_objects(Bucket=settings.BACKUP_S3_BUCKET, Delete={"Objects": old[i:i + 1000]})
    return len(old)


def run():
    """백업 한 번. 결과를 캐시에 남겨 Studio > Server 에서 보여줌."""
    if not configured():
        raise RuntimeError(".env 에 BACKUP_S3_BUCKET, BACKUP_AWS_ACCESS_KEY_ID, BACKUP_AWS_SECRET_ACCESS_KEY 가 필요해요.")
    if not cache.add(RUNNING_KEY, 1, 60 * 60):
        raise RuntimeError("이미 백업이 돌고 있어요.")
    started = time.monotonic()
    result = {"at": timezone.now().isoformat(), "ok": False}
    try:
        s3 = client()
        with tempfile.TemporaryDirectory() as tmp:
            path, key = dump_db(tmp)
            result["db_size"] = path.stat().st_size
            s3.upload_file(str(path), settings.BACKUP_S3_BUCKET, key)
            result["db_key"] = key
        result["uploaded"] = result["skipped"] = result["bytes"] = 0
        for prefix, attr in DIRS:
            up, skip, nbytes = sync_dir(s3, getattr(settings, attr), prefix)
            result["uploaded"] += up
            result["skipped"] += skip
            result["bytes"] += nbytes
        result["pruned"] = prune_db(s3, settings.BACKUP_KEEP_DAYS)
        result["ok"] = True
        return result
    except Exception as e:
        result["error"] = str(e)[:300]
        raise
    finally:
        result["seconds"] = round(time.monotonic() - started, 1)
        cache.set(STATUS_KEY, result, 400 * 24 * 60 * 60)
        cache.delete(RUNNING_KEY)


def start_in_background():
    """요청·cron 을 붙잡지 않도록 manage.py backup_s3 를 따로 띄움."""
    subprocess.Popen(
        [sys.executable, str(Path(settings.BASE_DIR) / "manage.py"), "backup_s3"],
        cwd=settings.BASE_DIR, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def due(now=None):
    """하루 한 번, BACKUP_HOUR(서버 시각) 이후 첫 실행 때."""
    now = timezone.localtime(now)
    if not configured() or now.hour < settings.BACKUP_HOUR:
        return False
    return cache.add(f"monitor:backup:day:{now.date().isoformat()}", 1, 26 * 60 * 60)
