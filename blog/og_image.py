"""글마다 링크 미리보기 카드 이미지(1200×630 PNG)를 그려서 저장해 둔다.

사진이 없는 공개 글의 og:image 로 쓰인다. 제목·카테고리·작성자·날짜가 바뀌면 다른 파일이 되어 새로 그려진다.
"""

import hashlib
from io import BytesIO
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1200, 630
FONT_DIR = Path(__file__).resolve().parent / "fonts"
BOLD = FONT_DIR / "NanumGothic-Bold.ttf"
XBOLD = FONT_DIR / "NanumGothic-ExtraBold.ttf"
GOLD = (212, 175, 55)
WHITE = (245, 245, 247)
MUTED = (170, 170, 180)
ACCENT = {"tech": ((10, 132, 255), "TECH"), "board": ((249, 115, 22), "BOARD"),
          "life": ((16, 185, 129), "LIFE"), "secret": ((239, 68, 68), "SECRET")}


def cache_key(post):
    author = post.author.get_full_name() or post.author.username if post.author else ""
    raw = f"v1|{post.title}|{post.category}|{author}|{post.published_at or post.created_at:%Y-%m-%d}"
    return hashlib.sha1(raw.encode()).hexdigest()[:10]


def storage_path(post):
    return f"og/posts/{post.id}-{cache_key(post)}.png"


def _wrap(draw, text, font, max_width, max_lines):
    """한글은 글자 단위, 영어는 단어 단위로 줄바꿈. 넘치면 마지막 줄을 … 로."""
    words = text.split(" ")
    lines, line = [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            line = candidate
            continue
        if line:
            lines.append(line)
            line = ""
        while draw.textlength(word, font=font) > max_width:  # 한 단어가 너무 길면 글자 단위로
            cut = len(word)
            while cut > 1 and draw.textlength(word[:cut], font=font) > max_width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        line = word
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > max_width:
            last = last[:-1]
        lines[-1] = last.rstrip() + "…"
    return lines


def render(post):
    accent, label = ACCENT.get(post.category, ((10, 132, 255), post.category.upper()))
    author = post.author.get_full_name() or post.author.username if post.author else ""
    when = timezone.localtime(post.published_at).strftime("%Y.%m.%d") if post.published_at else ""
    return render_card(title=post.title, pill=label, accent=accent, eyebrow="SMJ GALLERY · BLOG",
                       footer=" · ".join(x for x in (author, when) if x))


def render_card(title, pill="", accent=(10, 132, 255), eyebrow="SMJ GALLERY", subtitle="", footer=""):
    """카드 이미지 공통 틀: 위 로고·이름·배지 / 가운데 제목(+설명) / 아래 부가 정보·주소."""
    img = Image.new("RGB", (W, H), (15, 17, 21))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(15 + 8 * t), int(17 + 6 * t), int(21 + 16 * t)))
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    ImageDraw.Draw(glow).ellipse((780, -220, 1380, 380), fill=tuple(int(c * 0.45) for c in accent))
    glow = glow.filter(ImageFilter.GaussianBlur(130))
    img = Image.blend(img, Image.composite(glow, img, Image.new("L", (W, H), 110)), 1)
    d = ImageDraw.Draw(img)

    # 위: 로고 + 사이트 이름 + 배지
    d.ellipse((72, 62, 132, 122), outline=GOLD, width=3)
    d.text((102, 93), "MJ", font=ImageFont.truetype(str(XBOLD), 26), fill=GOLD, anchor="mm")
    d.text((150, 92), eyebrow, font=ImageFont.truetype(str(BOLD), 26), fill=MUTED, anchor="lm")
    if pill:
        pill_font = ImageFont.truetype(str(XBOLD), 22)
        pw = d.textlength(pill, font=pill_font) + 40
        d.rounded_rectangle((W - 72 - pw, 72, W - 72, 114), radius=21, fill=tuple(int(c * 0.28) for c in accent), outline=accent, width=2)
        d.text((W - 72 - pw / 2, 93), pill, font=pill_font, fill=WHITE, anchor="mm")

    # 가운데: 제목 (길이에 따라 글자 크기 조절) + 설명
    title = " ".join(str(title).split()) or "제목 없음"
    max_lines = 2 if subtitle else 3
    for size in (76, 68, 60, 54):
        font = ImageFont.truetype(str(XBOLD), size)
        lines = _wrap(d, title, font, W - 144, max_lines)
        if len(lines) <= max(1, max_lines - 1) or size == 54:
            break
    line_h = int(size * 1.32)
    sub_font = ImageFont.truetype(str(BOLD), 30)
    sub_lines = _wrap(d, " ".join(subtitle.split()), sub_font, W - 144, 2) if subtitle else []
    block = len(lines) * line_h + (len(sub_lines) * 44 + 18 if sub_lines else 0)
    top = max(170, 330 - block // 2)
    d.rectangle((72, top - 34, 72 + 64, top - 28), fill=accent)
    for i, line in enumerate(lines):
        d.text((72, top + i * line_h), line, font=font, fill=WHITE)
    y = top + len(lines) * line_h + 18
    for line in sub_lines:
        d.text((72, y), line, font=sub_font, fill=(200, 200, 208))
        y += 44

    # 아래: 부가 정보 / 주소
    small = ImageFont.truetype(str(BOLD), 26)
    if footer:
        d.text((72, H - 78), footer, font=small, fill=MUTED, anchor="ls")
    d.text((W - 72, H - 78), "smjgallery.kr", font=small, fill=GOLD, anchor="rs")

    out = BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def get_or_create(post):
    """저장된 이미지 경로를 돌려줌 (없으면 그려서 저장)."""
    path = storage_path(post)
    if not default_storage.exists(path):
        default_storage.save(path, ContentFile(render(post)))
    return path
