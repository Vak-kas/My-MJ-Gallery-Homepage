"""비공개 파일 저장소: nginx 가 공개로 서빙하는 MEDIA_ROOT 와 분리.
파일은 Django 뷰가 권한을 확인한 뒤 FileResponse 로만 내려준다."""

import os

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateStorage(FileSystemStorage):
	"""위치를 매번 settings.PRIVATE_MEDIA_ROOT 에서 읽음 (테스트에서 설정을 바꿔도 반영되도록)."""

	@property
	def base_location(self):
		return settings.PRIVATE_MEDIA_ROOT

	@property
	def location(self):
		return os.path.abspath(self.base_location)

	@property
	def base_url(self):
		return None  # 공개 URL 없음


def private_storage():
	return PrivateStorage()
