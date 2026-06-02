from io import BytesIO
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


PHOTO_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
PHOTO_MAX_DIMENSION = 2400
PHOTO_JPEG_QUALITY = 82


def photo_upload_to(instance, filename):
	stem = Path(filename).stem or "photo"
	safe_stem = slugify(stem) or "photo"
	return f"photo/{timezone.now():%Y/%m}/{safe_stem}-{uuid4().hex[:8]}.jpg"


class Photo(models.Model):
	title = models.CharField(max_length=120, blank=True)
	image = models.ImageField(upload_to=photo_upload_to)
	caption = models.TextField(blank=True)
	tags = models.CharField(max_length=255, blank=True)
	taken_at = models.DateTimeField(null=True, blank=True)
	width = models.PositiveIntegerField(default=0, editable=False)
	height = models.PositiveIntegerField(default=0, editable=False)
	is_visible = models.BooleanField(default=True)
	order = models.PositiveIntegerField(default=0)
	uploaded_by = models.ForeignKey(
		settings.AUTH_USER_MODEL,
		null=True,
		blank=True,
		on_delete=models.SET_NULL,
		related_name="uploaded_photos",
	)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["-taken_at", "-created_at", "-id"]

	def __str__(self):
		return self.title or f"Photo #{self.pk or 'new'}"

	def tag_list(self):
		raw_parts = [part.strip() for part in (self.tags or "").split(",")]
		return [part for part in raw_parts if part]

	def clean(self):
		super().clean()
		if self.image and getattr(self.image, "size", 0) > PHOTO_MAX_UPLOAD_BYTES:
			raise ValidationError({"image": "이미지 파일은 20MB 이하만 업로드할 수 있습니다."})

	def save(self, *args, **kwargs):
		update_fields = kwargs.get("update_fields")
		should_optimize = bool(self.image) and (
			not self.pk or update_fields is None or "image" in update_fields
		)

		if should_optimize:
			self._optimize_image()

		super().save(*args, **kwargs)

	def _optimize_image(self):
		if not self.image:
			return

		try:
			self.image.open("rb")
			image = Image.open(self.image)
			exif = image.getexif()
			image = ImageOps.exif_transpose(image)
		except (UnidentifiedImageError, OSError) as exc:
			raise ValidationError({"image": "지원되지 않거나 손상된 이미지 파일입니다."}) from exc

		if not self.taken_at:
			exif_dt = None
			for exif_key in (36867, 36868, 306):
				value = exif.get(exif_key) if exif else None
				if not value:
					continue
				try:
					parsed = datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S")
					exif_dt = timezone.make_aware(parsed, timezone.get_current_timezone())
					break
				except (ValueError, TypeError):
					continue
			self.taken_at = exif_dt

		if image.mode not in ("RGB", "L"):
			if "A" in image.getbands():
				background = Image.new("RGB", image.size, (255, 255, 255))
				background.paste(image, mask=image.getchannel("A"))
				image = background
			else:
				image = image.convert("RGB")
		elif image.mode == "L":
			image = image.convert("RGB")

		if max(image.size) > PHOTO_MAX_DIMENSION:
			image.thumbnail((PHOTO_MAX_DIMENSION, PHOTO_MAX_DIMENSION), Image.Resampling.LANCZOS)

		output = BytesIO()
		image.save(
			output,
			format="JPEG",
			quality=PHOTO_JPEG_QUALITY,
			optimize=True,
			progressive=True,
		)
		output.seek(0)

		self.width, self.height = image.size

		source_name = Path(self.image.name).stem if getattr(self.image, "name", "") else "photo"
		safe_source = slugify(source_name) or "photo"
		file_name = f"photo/{timezone.now():%Y/%m}/{safe_source}-{uuid4().hex[:8]}.jpg"
		self.image.save(file_name, ContentFile(output.read()), save=False)
