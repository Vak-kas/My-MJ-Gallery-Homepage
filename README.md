# MjGallery (서민재 갤러리)

개인 포트폴리오 + 블로그 + 갤러리를 통합한 Django 기반 웹 애플리케이션입니다.  
퍼블릭 페이지(`main`, `blog`, `gallery`)와 관리자 전용 콘텐츠 관리 공간(`studio`)으로 구성됩니다.

> 🌐 **서비스 URL: https://smjgallery.kr**

---

## 1) 핵심 기능

## 1.1 메인(Home)
- 프로필/연락처/링크
- Career(학력, 인턴십, 연구, 리더십, 멘토링)
- Activity / Award / Publication / Project / Skill 섹션 렌더링
- 프로젝트 상세(첨부파일 미리보기: 이미지/PDF/Office)
- Home 빠른 네비게이션 + 공통 상단 네비게이션

## 1.2 Blog Hub + 카테고리 블로그
- 카테고리: `Tech`, `Board`, `Life`, `Secret(관리자)`
- 피드 기능
	- 통합 검색(제목/요약/본문/태그)
	- 정렬(`최신`, `오래된`, `인기`)
	- 페이지당 표시 개수 선택(5/10/15/30)
	- 페이지네이션(처음/이전/번호/.../다음/마지막)
	- 내 글만 보기(로그인 사용자)
- 사이드 위젯
	- 인기글 순위
	- 태그 목록
	- 최근 댓글
	- 방명록

## 1.3 블로그 보안/운영 로직
- 글 공개 범위
	- `public` 전체공개
	- `private` 비공개
	- `protected` 비밀번호 보호글
- 보호글 비밀번호 시도 제한
	- 세션 기반, 5회 실패 시 10분 차단
- 보호글 잠금 전에는 조회수 증가 방지
- 보호글 내용 마스킹(카드/상세)
- 댓글/좋아요(PostLike, CommentLike)

## 1.4 Gallery
- Gallery 페이지(`/photos/`) 제공
- 관리자 업로드 기능
	- 드래그앤드롭 다중 파일
	- 업로드 전 미리보기/개별 삭제/전체 비우기
	- 태그 입력(쉼표 구분)
- 이미지 처리(서버측)
	- EXIF 방향 보정
	- 최대 변 2400px 리사이즈
	- JPEG 최적화 저장(품질 82)
	- 파일 크기 제한(10MB)
	- EXIF 촬영시각(`taken_at`) 추출
- 조회 기능
	- 최신순 정렬(촬영시각 우선, 없으면 업로드시각)
	- 태그 검색 + 인기 태그
- 관리자 삭제 기능
	- 카드 우상단 단건 삭제(`×`)
	- 다중 선택 삭제(클릭/드래그 범위선택 + 일괄 삭제)

## 1.5 Studio (관리자 전용 CMS)
- Profile / Career / Activity / Award / Publication / Certification / Project / Skill CRUD
- 가시성 토글, 정렬(순서 변경), 항목별 관리
- Posts 관리
	- 필터/정렬/페이지네이션
	- 일괄 삭제(확인 입력)
	- 공개 범위 변경

## 1.6 인증(Account)
- 회원가입 / 로그인 / 로그아웃
- 안전한 `next` 리다이렉트 검증
- 관리자(superuser) 로그인 시 Studio로 이동

---

## 2) 기술 스택

- Python 3.x
- Django 6.0.5
- SQLite (기본) / PostgreSQL (옵션)
- Pillow (이미지 처리)
- django-storages + boto3 (S3 옵션)
- Tailwind CSS(CDN)

의존성 목록: [requirements.txt](requirements.txt)

---

## 3) 프로젝트 구조

```
MjGallery/
├─ accounts/        # 인증(회원가입/로그인/로그아웃)
├─ blog/            # 블로그/댓글/좋아요/방명록
├─ main/            # 홈/갤러리/프로젝트 상세
├─ studio/          # 관리자 CMS
├─ config/          # Django 설정/루팅
├─ templates/       # 전역 템플릿
├─ static/          # 정적 파일
├─ media/           # 업로드 파일
└─ .github/workflows/deploy.yml
```

---

## 4) 로컬 실행 방법

## 4.1 가상환경/패키지 설치

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 4.2 환경 변수(.env)

루트에 `.env` 파일을 생성하고 최소 아래 값을 설정하세요.

```env
DJANGO_SECRET_KEY=your-secret-key
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost

# 선택: PostgreSQL
# DB_ENGINE=postgresql
# DB_NAME=mjgallery
# DB_USER=postgres
# DB_PASSWORD=...
# DB_HOST=localhost
# DB_PORT=5432

# 선택: S3
# USE_S3=True
# AWS_ACCESS_KEY_ID=...
# AWS_SECRET_ACCESS_KEY=...
# AWS_STORAGE_BUCKET_NAME=...
# AWS_S3_REGION_NAME=ap-northeast-2
```

## 4.3 DB 마이그레이션 + 관리자 생성

```bash
python manage.py migrate
python manage.py createsuperuser
```

## 4.4 실행

```bash
python manage.py runserver
```

---

## 5) 주요 URL

- `/` : Home
- `/blog/` : Blog Hub
- `/blog/tech/`, `/blog/board/`, `/blog/life/`, `/blog/secret/`
- `/blog/write/` : 글 작성(로그인 필요)
- `/photos/` : Gallery
- `/studio/` : 관리자 CMS (superuser)
- `/accounts/login/`, `/accounts/signup/`
- `/admin/` : Django Admin

---

## 6) 배포

GitHub Actions 워크플로우: [.github/workflows/deploy.yml](.github/workflows/deploy.yml)

- `main` 브랜치 push 시 Lightsail 서버에 SSH 배포
- 서버에서 `deploy.sh` 실행
- 이후 안전장치로:
	- `manage.py migrate --noinput`
	- `manage.py check`

---

## 7) 운영 시 주의사항

- 기능 추가 후에는 반드시 `migrate` 실행
- 이미지 업로드 한도/폼 업로드 한도는 `config/settings.py`에서 조정 가능
	- `DATA_UPLOAD_MAX_MEMORY_SIZE`
	- `FILE_UPLOAD_MAX_MEMORY_SIZE`
- 프로덕션에서는 `DEBUG=False`, 안전한 `ALLOWED_HOSTS` 사용

---

## 8) 라이선스

개인 포트폴리오 프로젝트 용도입니다. 필요 시 별도 라이선스를 추가하세요.
