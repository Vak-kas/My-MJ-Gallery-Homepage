# MjGallery (서민재 갤러리)

개인 포트폴리오 · 블로그 · 갤러리 · 웹 도구를 하나로 묶은 Django 웹 애플리케이션입니다.
누구나 보는 퍼블릭 페이지(`main`, `blog`, `gallery`, `tools`)와 관리자 전용 관리 공간(`studio`)으로 구성됩니다.

> 🌐 **서비스 URL: https://smjgallery.kr**

---

## 1) 핵심 기능

### 1.1 메인 (Home)
- 프로필 / 연락처 / 링크
- Career(학력, 인턴십, 연구, 리더십, 멘토링), Activity, Award, Publication, Certification, Project, Skill 섹션
- 프로젝트 상세 (첨부파일 미리보기: 이미지 / PDF / Office)
- 공통 상단 내비게이션 (관리자에게만 Studio · 🔔 알림 표시)

### 1.2 블로그
- 카테고리: `Tech`, `Board`, `Life`, `Secret(관리자)`
- 통합 검색(제목/요약/본문/태그), 정렬(최신·오래된·인기), 페이지당 개수 선택, 페이지네이션, 내 글만 보기
- 사이드 위젯: 인기글, 태그, 최근 댓글, 방명록
- 공개 범위: `public` 전체공개 / `private` 비공개 / `protected` 비밀번호 보호
  - 보호글 비밀번호 5회 실패 시 10분 차단, 잠금 해제 전 조회수 미증가, 카드·상세 내용 마스킹
- **발행 / 임시저장** 구분: 임시저장 글은 작성자만 보이고, 이어서 쓰기·발행 취소 지원 (처음 발행일 유지)
- 댓글 · 좋아요(글/댓글)
- **방명록은 로그인한 회원만** 작성 가능 + 작성 빈도 제한 (스팸 방지)

### 1.3 노션형 에디터 (Tiptap)
- `/` 슬래시 메뉴로 블록 추가: 제목, 목록, 체크리스트, 인용, 코드, 표, 토글, 수식(KaTeX), 구분선, 이미지, 링크 카드
- 블록 왼쪽 핸들로 드래그 이동 · 블록 메뉴, 텍스트 선택 시 서식 툴바
- 이미지 붙여넣기 / 끌어놓기 업로드 (큰 이미지는 업로드 전 브라우저에서 축소)
- URL 붙여넣기 시 링크 미리보기 카드
- 저장 형식: `{"format":"tiptap","version":1,"doc":...}` → 서버에서 HTML 로 렌더링(`blog/content.py`), 예전 형식 글도 그대로 표시
- 소스: `frontend/editor/` (빌드 결과 `static/editor/mj-editor.js` 는 저장소에 포함)

### 1.4 Gallery
- `/photos/` 사진 갤러리, 태그 검색 + 인기 태그, 촬영시각(EXIF) 우선 최신순
- 관리자 업로드: 드래그앤드롭 다중 파일, 미리보기 / 개별 삭제, 태그 입력
- 서버측 처리: EXIF 방향 보정, 최대 변 2400px 리사이즈, JPEG 품질 82 최적화, 10MB 제한
- 관리자 삭제: 단건(`×`) / 클릭·드래그 범위 선택 일괄 삭제

### 1.5 Tool (`/tools/`)
허브는 **누구나 / 🔒 회원 전용 / 🛠 관리자 전용** 칸으로 나뉘고, 도구가 없는 칸은 보이지 않습니다 (`tools/registry.py` 의 `access`).

| 도구 | 설명 | 이용 |
|---|---|---|
| 🔑 키 생성기 | 길이·문자 종류·형식(Hex, Base64, UUID, PIN, API 키) 비밀번호/키 생성, RSA·ECDSA·Ed25519 키 쌍 PEM·OpenSSH 내보내기. 모두 브라우저 안에서만 생성 | 누구나 |
| 📋 클립보드 공유 | 계정별 개인 클립보드에 텍스트·이미지·파일을 ⌘V 로 붙여넣고 다른 기기에서 복사/다운로드, 5초 간격 자동 동기화 (파일 20MB, 계정 200MB·200개) | 로그인 회원 |
| ⚡ 인터넷 속도 측정 | 이 서버와 실제 데이터를 주고받아 다운로드·업로드·ping 을 실시간 그래프로 측정 (회원별 10분·하루 사용량 한도) | 로그인 회원 |
| 🔍 내 IP · 접속 정보 | 공인 IP·IPv4/6·호스트 이름·브라우저/기기 정보, 버튼을 누르면 RDAP 로 통신사·국가 조회 | 누구나 |
| 🧮 인코딩 · 해시 | Base64·URL·Hex·HTML·유니코드 변환, MD5·SHA·HMAC·파일 해시, JWT 보기 (브라우저 안에서만) | 누구나 |
| 📡 포트 · 핑 · DNS 체크 | 이 서버에서 TCP 포트·ping·경로 추적·DNS 레코드 확인 (내부 주소 차단, 10분 20회) | 로그인 회원 |
| 🔗 단축 URL | `smjgallery.kr/s/<코드>` 단축 링크, 클릭 수, 유효 기간 | 만들기는 회원, 열기는 누구나 |
| 🤫 1회용 비밀 메모 | 브라우저에서 AES-GCM 암호화(키는 링크 `#` 뒤에만), 한 번 열면 서버에서 삭제 | 만들기는 회원, 열기는 누구나 |
| ▦ QR 코드 만들기 | 주소·글·Wi-Fi·연락처·문자·메일 QR, 테마·점 모양·그라데이션·모서리 눈·테두리 문구·가운데 사진(사진 색 자동 테마), ✨ AI 스타일 추천(회원, 하루 20번), 실시간 스캔 확인, PNG·SVG 저장, 사진 속 QR 읽기 (브라우저 안에서만) | 누구나 |
| { } JSON 정리 | 정리·한 줄로·키 정렬, 느슨한 입력(주석·끝 쉼표), 오류 줄·칸 표시, 접는 트리·경로 복사, 문자열 JSON 풀기, CSV 변환 | 누구나 |
| .* 정규식 테스트 | 실시간 하이라이트, 그룹·이름 그룹 표, 바꾸기, 패턴 풀이, 자주 쓰는 패턴, 1초 넘는 패턴 자동 중단(Web Worker) | 누구나 |
| ⇄ 전이중/반이중 계산기 | 회선 속도·프레임 크기·전환 시간으로 Full/Half Duplex 처리량 비교, Wi-Fi 6/7 프리셋 | 누구나 |
| 🌐 서브넷 계산기 | IP/CIDR·마스크로 네트워크·브로드캐스트·호스트 범위, 2진수 표시, 서브넷 분할 | 누구나 |
| 📺 라이브 방송 | 화면·소리, 웹캠·마이크를 WebRTC 로 실시간 방송, 채팅, 직접 연결이 막히면 TURN 서버 중계 | 방송은 회원(한도), 시청은 링크만 있으면 누구나 |
| 📡 데이터 전송 | 방을 열고 링크를 나눠 브라우저끼리 파일 실시간 전송(서버 저장 없음), 받는 사람이 없으면 **맡겨두기**(최대 2GB, 유효시간 후 자동 삭제), 프로그램 바이트 스트림·GNU Radio ZMQ IQ 중계 | 방 만들기는 로그인 회원(한도: 동시 1개·하루 3개·60분·8MB/s·3GB, 관리자는 무제한), 맡겨두기 업로드는 관리자, 받는 쪽은 링크만 있으면 로그인 없이 |

- 데이터 전송 중계 데몬 `relay/mj_relay.py` (asyncio + pyzmq + aiohttp, systemd 서비스 `mj-relay`) — 자세한 내용은 [relay/README.md](relay/README.md)
- 맡겨두기·클립보드 파일은 nginx 가 서빙하지 않는 `private_media/` 에 저장하고, Django 가 권한 확인 후에만 내려줌

### 1.6 회원 · 가입 승인
- 회원가입: 아이디, **이름(실명)**, 이메일, 비밀번호, 가입 인사(선택) + **개인정보 수집·이용 동의(필수)**
- 가입 신청 시 계정은 **승인 대기(비활성)** → 관리자가 승인해야 로그인 가능
- 로그인 시 승인 대기 / 거절 / 정지 사유 안내, 안전한 `next` 리다이렉트 검증
- 관리자 로그인 시 Studio 로 이동

### 1.7 관리자 알림
- Logout 옆 **🔔 + 안 읽은 개수** (관리자에게만 표시)
- 알림 종류: 가입 요청, 다른 회원의 댓글 · 방명록 · 새 글 발행 (관리자 본인 활동은 제외)
- `/notifications/`: 종류별 필터, 누르면 읽음 처리 후 해당 화면으로 이동, 모두 읽음 / 읽은 알림 지우기
- **카카오톡 '나에게 보내기'** 연동: 알림 화면에서 카카오톡 연결 → 새 알림을 나와의 채팅으로 전송 (토큰 자동 갱신)

### 1.8 Studio (관리자 전용 CMS, `/studio/`)
- Profile / Career / Activity / Award / Publication / Certification / Skill / Project CRUD, 노출 토글, 순서 변경
- **Posts**: 검색·작성자·기간·**제목 포함(예: 555)** 필터, 발행/임시저장 상태 필터, 공개 범위 변경
  - 일괄 작업(발행, 발행 취소, 공개 범위, 삭제)을 체크한 글 또는 **필터 결과 전체(모든 페이지)** 에 적용
- **Community**: 방명록 · 댓글 검색, 숨기기 / 다시 보이기 / 삭제, 필터 결과 전체 처리
  - 🔗 **단축 링크**: 모든 회원의 단축 링크를 주소·코드·회원으로 검색, 선택/필터 결과 삭제
  - 🧹 **키워드 일괄 정리**: 글 제목·본문, 댓글, 방명록, 단축 링크 주소에서 키워드 포함 항목을 미리보기 후 한 번에 삭제
- **Users**: 회원 검색(아이디·이메일·실명), 승인 대기 / 활성 / 정지·거절 / 관리자 필터, 글·댓글·방명록 수
  - 승인 · 거절 · 정지 · **정지 + 작성한 콘텐츠 전부 삭제** · 계정 삭제 (본인·관리자 계정 제외)
- **Settings**: 상단 메뉴(Home·Blog·Tool·Gallery) 이름·순서·공개 범위(모두 / 로그인 회원만 / 숨김), 홈 화면 섹션 켜기·끄기·순서
  - 숨기거나 회원 전용으로 바꾼 메뉴는 페이지 자체도 막힘 (데이터 전송·맡겨두기·비밀 메모처럼 링크로 여는 페이지는 계속 열림)
- **Security**: 보안 기록과 차단 (기록은 90일 뒤 자동 정리, `python manage.py security_cleanup`)
  - 로그인 기록(성공·실패·잠김), 같은 아이디 15분 5회 / 같은 IP 15분 10회 실패 시 15분 잠금
  - **관리자 계정이 처음 보는 IP 에서 로그인하면 🔔 + 카톡 알림**
  - 글·댓글·방명록 작성 IP·브라우저 기록, IP 로 검색, **증거 CSV 내보내기**
  - IP·대역 차단(기간 지정, 내 IP·너무 넓은 대역은 막지 않음) → 차단된 IP 는 사이트 전체 403
- 삭제 작업은 모두 `DELETE` 확인 문구 입력 필요

---

## 2) 기술 스택

- Python 3.x, **Django 6.0.5**
- SQLite (기본) / PostgreSQL (옵션), django-storages + boto3 (S3 옵션)
- Pillow (이미지 처리)
- Tailwind CSS (CDN), Tiptap 3 + esbuild (에디터)
- pyzmq + aiohttp (데이터 전송 중계 데몬)
- gunicorn + nginx, AWS Lightsail, GitHub Actions 배포

의존성 목록: [requirements.txt](requirements.txt)

---

## 3) 프로젝트 구조

```
MjGallery/
├─ accounts/          # 회원가입(승인 요청)/로그인/로그아웃
├─ blog/              # 블로그/댓글/좋아요/방명록, 에디터 콘텐츠 렌더링(content.py)
├─ main/              # 홈/갤러리/프로젝트 상세
├─ studio/            # 관리자 CMS (Posts, Community, Users 포함)
├─ notifications/     # 관리자 알림, 카카오톡 푸시
├─ security/          # 로그인 기록·잠금, IP 차단 미들웨어, 작성 IP 보관 기간 정리
├─ tools/             # Tool 메뉴 (키 생성기, 클립보드, 속도 측정, 계산기, 데이터 전송·맡겨두기)
├─ relay/             # 데이터 전송 중계 데몬(mj_relay.py), CLI(mj_stream.py), 서버 설치 스크립트
├─ frontend/editor/   # 노션형 에디터 소스 (Tiptap)
├─ config/            # Django 설정/라우팅
├─ templates/         # 전역 템플릿
├─ static/            # 정적 파일 (static/editor/mj-editor.js 빌드 결과 포함)
├─ media/             # 공개 업로드 파일
├─ private_media/     # 비공개 업로드(클립보드·맡겨두기), git 제외
└─ .github/workflows/deploy.yml
```

---

## 4) 로컬 실행

### 4.1 가상환경 / 패키지 설치
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4.2 환경 변수 (.env)
루트에 `.env` 파일을 만들고 필요한 값을 넣으세요.

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

# 선택: 데이터 전송 중계 데몬 (relay/README.md 참고)
# RELAY_API_KEY=...
# RELAY_PORT_MIN=5550
# RELAY_PORT_MAX=5599
# RELAY_PUBLIC_HOST=smjgallery.kr

# 선택: QR 코드 AI 스타일 추천 (Claude API)
# ANTHROPIC_API_KEY=sk-ant-...
# ANTHROPIC_MODEL=claude-haiku-5-5

# 선택: 관리자 알림 카카오톡
# SITE_URL=https://smjgallery.kr
# KAKAO_REST_API_KEY=...        # 카카오 개발자 콘솔 > 플랫폼 키 > REST API 키
# KAKAO_CLIENT_SECRET=...       # 같은 키의 클라이언트 시크릿
```

카카오톡 알림을 쓰려면 카카오 개발자 콘솔에서
카카오 로그인 ON, 리다이렉트 URI `https://<도메인>/notifications/kakao/callback/`,
동의항목 **카카오톡 메시지 전송(talk_message)** 선택 동의를 설정한 뒤, 사이트 🔔 알림 화면에서 **카카오톡 연결**을 누르세요.

### 4.3 DB 마이그레이션 + 관리자 생성
```bash
python manage.py migrate
python manage.py createsuperuser
```

### 4.4 실행
```bash
python manage.py runserver
```

### 4.5 에디터 수정 시 (선택)
```bash
cd frontend/editor
npm install
npm run build      # static/editor/mj-editor.js 생성 (개발 중에는 npm run watch)
```

### 4.6 테스트
```bash
python manage.py test
python -m unittest discover -s relay/tests -t .
```

---

## 5) 주요 URL

| URL | 설명 |
|---|---|
| `/` | Home |
| `/blog/`, `/blog/tech/`, `/blog/board/`, `/blog/life/`, `/blog/secret/` | 블로그 |
| `/blog/write/` | 글 작성 (로그인 필요) |
| `/photos/` | Gallery |
| `/tools/` | Tool 메뉴 (`keygen/`, `clipboard/`, `speedtest/`, `duplex/`, `subnet/`, `stream/`, `share/`) |
| `/studio/` | 관리자 CMS (`posts/`, `community/`, `users/` 등) |
| `/notifications/` | 관리자 알림 · 카카오톡 연결 |
| `/accounts/signup/`, `/accounts/login/` | 가입 신청 / 로그인 |
| `/admin/` | Django Admin |

---

## 6) 배포

GitHub Actions 워크플로우: [.github/workflows/deploy.yml](.github/workflows/deploy.yml)

- `main` 브랜치 push 시 Lightsail 서버에 SSH 접속해 `deploy.sh` 실행
  - `git pull` → `pip install` → `migrate` → `collectstatic` → gunicorn 재시작 → `mj-relay` 재시작
- 데이터 전송 중계 데몬 최초 설치: `sudo bash relay/deploy/install.sh` + 방화벽 TCP `5550-5599` 개방 ([relay/README.md](relay/README.md))

---

## 7) 운영 메모

- 관리 명령
  - `python manage.py cleanup_shared_files` — 만료된 맡겨두기 파일 정리 (업로드·다운로드 때도 자동 정리)
  - `python manage.py clear_guestbook` — 방명록 정리 (평소에는 Studio → Community 사용 권장)
- 업로드 한도는 `config/settings.py` 의 `DATA_UPLOAD_MAX_MEMORY_SIZE`, `FILE_UPLOAD_MAX_MEMORY_SIZE` (nginx `client_max_body_size` 와 함께 조정)
- 프로덕션에서는 `DEBUG=False`, 안전한 `ALLOWED_HOSTS` 사용, `.env` 는 git 에 올리지 않기
- 회원 개인정보(이름·이메일)는 가입 승인·회원 관리 목적으로만 사용하고, 탈퇴·거절 후 요청 시 삭제

---

## 8) 라이선스

개인 포트폴리오 프로젝트 용도입니다. 필요 시 별도 라이선스를 추가하세요.
