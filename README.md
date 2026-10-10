# MjGallery (서민재 갤러리)

개인 포트폴리오 · 블로그 · 갤러리 · 웹 도구를 하나로 묶은 Django 웹 애플리케이션입니다.
누구나 보는 퍼블릭 페이지(`main`, `blog`, `gallery`, `tools`, `games`)와 관리자 전용 관리 공간(`studio`)으로 구성됩니다.

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
- **시리즈 글**: 글쓰기 화면에서 시리즈 이름·몇 편 입력 → 글 위 목차(n/전체편), 아래 이전·다음 편 버튼, 시리즈 페이지 `/blog/series/<slug>/`
- RSS `/blog/feed/` (공개 글 최신 20개)

### 1.3 노션형 에디터 (Tiptap)
- `/` 슬래시 메뉴로 블록 추가: 제목, 목록, 체크리스트, 인용, 코드, 표, 토글, 수식(KaTeX), 구분선, 이미지, 링크 카드
- 블록 왼쪽 핸들로 드래그 이동 · 블록 메뉴, 텍스트 선택 시 서식 툴바
- 이미지 붙여넣기 / 끌어놓기 업로드 (큰 이미지는 업로드 전 브라우저에서 축소)
- URL 붙여넣기 시 링크 미리보기 카드
- 저장 형식: `{"format":"tiptap","version":1,"doc":...}` → 서버에서 HTML 로 렌더링(`blog/content.py`), 예전 형식 글도 그대로 표시
- 소스: `frontend/editor/` (빌드 결과 `static/editor/mj-editor.js` 는 저장소에 포함)

### 1.4 링크 미리보기 · 검색 노출 · 다크 모드
- 모든 페이지에 Open Graph·트위터 카드 메타 태그 → 카톡·디스코드 등에 링크를 보내면 카드로 표시
  - 블로그 글: 제목·요약·대표 이미지(커버 → 본문 첫 사진 → **제목이 들어간 카드 이미지 자동 생성**), 비밀번호 글은 내용·이미지 숨김
  - Tool 목록·각 도구·블로그·카테고리·갤러리·시리즈·라이브 방송 링크도 **페이지 전용 카드**를 자동 생성 (`/og/<종류>/<키>.png`, `media/og/` 에 저장·재사용)
  - 카드 글꼴: 나눔고딕(SIL OFL, `blog/fonts/`), 기본 이미지 `static/images/og-default.png`
- `/sitemap.xml`(공개 페이지·글, Settings 에서 닫은 메뉴 제외), `/robots.txt`(관리·공유 링크 크롤링 금지), 개인·공유 페이지는 noindex
- **다크 모드**: `scripts/gen_dark_css.py` 가 템플릿 전체의 색(클래스·`<style>`)을 훑어 `static/css/theme-dark.css` 를 자동 생성 — 밝은 배경은 어둡게, 대비가 모자란 글자는 밝게

### 1.5 Gallery
- `/photos/` 사진 갤러리, 태그 검색 + 인기 태그, 촬영시각(EXIF) 우선 최신순
- 관리자 업로드: 드래그앤드롭 다중 파일, 미리보기 / 개별 삭제, 태그 입력
- 서버측 처리: EXIF 방향 보정, 최대 변 2400px 리사이즈, JPEG 품질 82 최적화, 10MB 제한
- 관리자 삭제: 단건(`×`) / 클릭·드래그 범위 선택 일괄 삭제

### 1.6 Tool (`/tools/`)
허브는 쓰임새별 **분류**(`tools/registry.py` 의 `CATEGORIES`, 도구마다 `category`)로 나뉘고, 위쪽 분류 칩·검색창으로 걸러 볼 수 있습니다 (`/tools/#network` 처럼 분류 링크 공유 가능, 검색 후 하나만 남으면 Enter 로 열기).
회원 전용 도구는 카드에 **🔒 회원** 표시, 관리자 전용 도구(`access: "admin"`)는 관리자에게만 맨 아래 칸으로 보입니다.

**📝 문서 · 공부**

| 도구 | 설명 | 이용 |
|---|---|---|
| 📄 PDF 도구 | PDF·사진 여러 개 합치기, 페이지 끌어서 순서 바꾸기·돌리기·빼기, 선택한 페이지만 / 페이지마다 따로 저장, 사진은 A4 맞춤 또는 원래 크기 (pdf.js + pdf-lib, 브라우저 안에서만) | 누구나 |
| ✍️ 글자 수 세기 | 공백 포함/제외 글자 수, 바이트(한글 2바이트·UTF-8), 단어·문장·문단, 원고지 매수, 읽기·말하기 시간, 목표 글자 진행 막대, 자주 쓴 낱말, 긴 문장 찾기 (브라우저 안에서만) | 누구나 |
| 🖼 이미지 도구 | 용량 줄이기("N KB/MB 이하로": 화질 자동 탐색 + 크기 줄이기), 크기·형식 변환(JPG·PNG·WebP, HEIC 열기), 돌리기·뒤집기·자르기(1:1·4:3·3:4 증명사진·16:9), 📍 위치·카메라·날짜 정보 표시 후 저장하면 모두 제거, 여러 장 ZIP (브라우저 안에서만, HEIC 는 heic2any) | 누구나 |
| 📷 사진 글자 추출 | 사진·캡처·문서 속 글자를 뽑아 바로 고치고 복사. 기본은 **무료(서버 Tesseract, 한글+영어)** + 인식 신뢰도 표시, 손글씨·칠판·표는 **✨AI 로 다시 읽기**(회원, 표는 마크다운 표로). 줄 그대로 / 문단으로 이어서, 여러 장(5장)·⌘V·HEIC, 모두 복사·.txt. 사진은 저장 안 함 | 무료는 누구나(10분 10장, 회원 30장, VIP 3배), AI 는 회원 |
| 📖 표준 서재 | **VIP 회원·관리자.** 갖고 있는 표준 PDF(IEEE 802.11be·ax, 3GPP TS 등, 95MB·6000쪽까지, 계정당 800MB·15개)를 올리면 따로 뜬 프로세스(`manage.py stdlib_index`)가 PyMuPDF 로 절 번호 단위로 나눔 — 같은 높이 줄 합치기(번호·제목), 머리말·꼬리말·목차 줄 빼기, 표·그림 제목(IEEE `Table 36-30—` / 3GPP `Table 6.1.3.1-1:`), 긴 절은 1800자 조각. 찾기: PostgreSQL 전문 검색(영어 어간, GIN 색인 `tools_stdchunk_fts`, 붙여 쓴 변수 이름 `drx-InactivityTimer` 도 찾게 이웃 단어 붙인 형태 같이), 절 번호·표 번호 바로 찾기, 한국어 용어(펑처링 → puncturing …), 변경 이력은 순위 낮춤, 검색어 강조·절 전체 펼치기·**원문 쪽을 그림으로**(PyMuPDF 렌더). ✨ 묻기: 고른 절 또는 다시 찾은 상위 절을 같은 절 조각까지 묶어 근거로, 답에 [n]·절·쪽·원문 인용. **문서는 올린 사람만 봄**(IEEE 문서 재배포가 되지 않게, 비공개 폴더 `private_media/stdlib/<user>/`) | VIP |
| 📑 논문 찾기 | 키워드로 논문 검색 — OpenAlex(제목·초록, 선택 시 본문) / arXiv 최신. 통신 약어·한국어를 넓혀 찾기(NTN → non-terrestrial·satellite communication…, 위성 → satellite), 직접 AND·OR·NOT 도 됨. 관련도 상위 100편을 받아 인용순·최신순으로 다시 정렬, 기간·통신/전자 분야·원문 공개·저널/학회(TWC·JSAC·ICC·GLOBECOM…) 거르기, 초록 검색어 강조, 참고문헌·인용한 논문 꼬리 물기, BibTeX·IEEE 복사·내 참고문헌(인용 도구)으로, 📌 내 논문함(회원, 중요·읽기 상태·메모·.bib). **📖 섹션 보기**: arXiv HTML 원문(번호가 없으면 제목으로 arXiv 판 찾기, 그래도 없으면 학교에서 받은 PDF 올리기 — 저장 안 함)을 초록·서론·기여·관련 연구·시스템 모델·문제 정의·제안 기법·분석·시뮬레이션·결론으로 나눠 보기, 수식 KaTeX, 서론 문단 역할(배경·기존 연구·한계·이 논문이 한 일·구성) 자동 표시, 기여 목록 뽑기, 인용 번호 → 참고문헌 말풍선·서론 속 인용 목록(눌러서 찾기), **나란히 보기**(최대 8편의 같은 섹션·기여를 이어서). **✨ AI 정리**(회원, 기존 AI 하루 한도에서): 한 논문 구조(시나리오·채널·공격/간섭 모델·목표·기법·지표·비교 기법·가정·한계·키워드), 서론 흐름 분석(문단별 역할·요지·전체 흐름·배울 점·다시 써도 되는 표현 패턴), 나란히 보기 비교표(CSV·마크다운)와 접근법별 묶음·연구 공백 후보. **🇰🇷 섹션 번역**: ✨ AI 번역(전문 용어 병기, 수식·인용은 자리표시로 지켜서 다시 끼움, 회원 글자 한도로 나눠 보냄, 같은 글은 30일 캐시) 또는 🆓 크롬 내장 번역(Translator API, 기기 안에서 무료), 원문 같이 보기, 수식·인용에 translate="no" 를 붙여 브라우저 번역도 안 깨짐. 공개 논문 정리 결과는 내용 해시로 30일 캐시해서 같은 논문은 AI 를 다시 안 부름 결과 하루 캐시, 외부 조회 10분 횟수 제한, OpenAlex 남은 하루 예산 확인 | 누구나 (논문함은 회원) |
| 📚 논문 인용 만들기 | DOI·arXiv 번호·논문 제목·3GPP 규격 번호(`TS 38.321`, `TR 38.901 v17.0.0`)를 한 줄에 하나씩(최대 20개) 넣으면 BibTeX·APA 7·IEEE·MLA 9·Chicago. 제목은 Crossref+arXiv 에서 찾아 후보 고르기, 3GPP 는 3GPP 포털에서 제목·릴리스별 버전·날짜를 읽고 BibTeX 는 [3gpp-citations](https://github.com/martisak/3gpp-citations) 형식. 갖고 있는 BibTeX 붙여넣어 변환(브라우저 안), 이탤릭 포함 복사, 내 참고문헌 목록(브라우저 저장)·.bib 저장. 결과는 캐시(논문 30일·검색 1일·3GPP 7일), 외부 조회는 10분 횟수 제한 | 누구나 |
| 🎓 학점 계산기 | 과목별/학기 합계 입력, 4.5·4.3 제, P/NP·F, 전공 평점, 목표 누적 평점까지 필요한 평균, 4.5 ↔ 4.3 ↔ 100점 환산(비례·×20+10·직접 공식). 성적은 브라우저에만 저장 | 누구나 |
| 🔀 글 비교 | 두 글을 줄·단어·글자 단위로 비교(Myers diff), 한 줄 보기/나란히 보기, 바뀐 줄 안 글자 강조, 공백·대소문자 무시 (브라우저 안에서만), ✨ **AI 바뀐 내용 요약**(무엇이·꼭 확인할 점, 회원) | 누구나 |

**🔗 공유 · 전송**

| 도구 | 설명 | 이용 |
|---|---|---|
| 📡 데이터 전송 | 방을 열고 링크를 나눠 브라우저끼리 파일 실시간 전송(서버 저장 없음), 받는 사람이 없으면 **맡겨두기**(최대 2GB, 유효시간 후 자동 삭제), 프로그램 바이트 스트림·GNU Radio ZMQ IQ 중계 | 방 만들기는 로그인 회원(한도: 동시 1개·하루 3개·60분·8MB/s·3GB, 관리자는 무제한), 맡겨두기 업로드는 관리자, 받는 쪽은 링크만 있으면 로그인 없이 |
| 📅 팀플 일정 맞추기 | 날짜(달력에서 여러 날)·시간대·칸 단위(15·30·60분)로 링크를 만들면 각자 되는 시간을 드래그로 칠함, 겹칠수록 진하게·칸별 가능한 사람, **모두 되는 시간**(없으면 가장 많이 되는 시간) 정리, 4초마다 자동 갱신, 다른 기기는 비밀번호(선택)로, 마지막 날 + 14일 뒤 자동 삭제 | 만들기는 회원(30개), 참여는 링크만 있으면 누구나(일정당 60명) |
| 📋 클립보드 공유 | 계정별 개인 클립보드에 텍스트·이미지·파일을 ⌘V 로 붙여넣고 다른 기기에서 복사/다운로드, 5초 간격 자동 동기화 (파일 20MB, 계정 200MB·200개) | 로그인 회원 |
| 🔗 단축 URL | `smjgallery.kr/s/<코드>` 단축 링크, 클릭 수, 유효 기간 | 만들기는 회원, 열기는 누구나 |
| 🤫 1회용 비밀 메모 | 브라우저에서 AES-GCM 암호화(키는 링크 `#` 뒤에만), 한 번 열면 서버에서 삭제 | 만들기는 회원, 열기는 누구나 |
| ▦ QR 코드 만들기 | 주소·글·Wi-Fi·연락처·문자·메일 QR, 테마·점 모양·그라데이션·모서리 눈·테두리 문구·가운데 사진(사진 색 자동 테마), ✨ AI 스타일 추천(회원), 실시간 스캔 확인, PNG·SVG 저장, 사진 속 QR 읽기 (브라우저 안에서만) | 누구나 |
| 📺 라이브 방송 | 화면·소리, 웹캠·마이크를 WebRTC 로 실시간 방송, 채팅, 직접 연결이 막히면 TURN 서버 중계 | 방송은 회원(한도), 시청은 링크만 있으면 누구나 |

**🌐 네트워크**

| 도구 | 설명 | 이용 |
|---|---|---|
| 🔍 내 IP · 접속 정보 | 공인 IP·IPv4/6·호스트 이름·브라우저/기기 정보, 버튼을 누르면 RDAP 로 통신사·국가 조회 | 누구나 |
| ⚡ 인터넷 속도 측정 | 이 서버와 실제 데이터를 주고받아 다운로드·업로드·ping 을 실시간 그래프로 측정 (회원별 10분·하루 사용량 한도) | 로그인 회원 |
| 📡 포트 · 핑 · DNS 체크 | 이 서버에서 TCP 포트·ping·경로 추적·DNS 레코드 확인 (내부 주소 차단, 10분 20회), ✨ **AI 결과 풀이**(정상·확인·문제 + 다음 단계) | 로그인 회원 |
| 🌐 서브넷 계산기 | IP/CIDR·마스크로 네트워크·브로드캐스트·호스트 범위, 2진수 표시, 서브넷 분할 | 누구나 |
| ⇄ 전이중/반이중 계산기 | 회선 속도·프레임 크기·전환 시간으로 Full/Half Duplex 처리량 비교, Wi-Fi 6/7 프리셋 | 누구나 |

**🛠 개발 · 보안**

| 도구 | 설명 | 이용 |
|---|---|---|
| { } JSON 정리 | 정리·한 줄로·키 정렬, 느슨한 입력(주석·끝 쉼표), 오류 줄·칸 표시, 접는 트리·경로 복사, 문자열 JSON 풀기, CSV 변환 | 누구나 |
| .* 정규식 테스트 | 실시간 하이라이트, 그룹·이름 그룹 표, 바꾸기, 패턴 풀이, 자주 쓰는 패턴, 1초 넘는 패턴 자동 중단(Web Worker), ✨ **말로 만들기**("휴대폰 번호 찾기" → 패턴·설명·주의점·예시 글, 회원) | 누구나 |
| 💻 깃허브 코드 찾기 | 💡 아이디어(한국어) → ✨AI 가 깃허브 검색어 3~4개로 바꿔 찾아 합침(여러 검색어에 같이 나온 것 먼저) / 🔎 키워드 / 📑 논문 코드(arXiv 번호·제목이 README·설명에 든 저장소, 논문 찾기 카드의 💻 코드 버튼). 언어·별·최근 수정·정렬, 별·포크·언어·마지막 수정·토픽, **라이선스 안내**(MIT 등 자유 / GPL 주의 / 없음 = 원칙상 사용 불가), README 보기, git clone 복사, ✨ 내 아이디어와 맞는지 0~5점·바로 사용/참고만·추천·직접 만들 때 팁. GitHub REST 검색(선택 `GITHUB_TOKEN`), 검색 6시간·README 하루 캐시, 10분 횟수 제한 | 누구나 (✨AI 는 회원) |
| 🧮 인코딩 · 해시 | Base64·URL·Hex·HTML·유니코드 변환, MD5·SHA·HMAC·파일 해시, JWT 보기 (브라우저 안에서만) | 누구나 |
| 📶 Wi‑Fi 계산기 | ⚡ 속도: Wi‑Fi 4·5·6/6E·7(802.11n/ac/ax/be) × 대역폭 20~320 MHz × 공간 스트림 × GI → MCS 별 PHY 속도 표(변조·부호율·최소 수신 감도), 실제 기대 속도(효율 %)·1 GB 받는 시간, 802.11ac 정의 안 된 조합 경고. 📍 신호 세기: 대역·거리·출력·안테나·공간(거리 지수 n)·벽 종류별 개수 → RSSI·이 자리 최대 MCS·예상 속도, 거리별 그래프. 🗂 채널: 2.4·5·6 GHz 채널과 40·80·160·320 MHz 묶음 경계, DFS 구역, 주변 공유기 겹침 확인·2.4 GHz 추천 채널. 브라우저 안에서만 | 누구나 |
| 📡 링크 버짓 계산기 (위성·NTN) | 궤도 고도·앙각으로 거리(slant range)·자유공간 경로 손실, EIRP(밀도 또는 전력+이득)·G/T(직접 또는 이득+NF+안테나 온도)·대기·그림자·섬광·편파 손실로 C/N₀·SNR·여유·섀넌 용량, 수신·잡음 전력, 지연(편도·왕복), 도플러, 위성 속도·주기·보이는 시간. 3GPP TR 38.821 Set-1/2 × GEO·LEO-1200·LEO-600 × S 대역 휴대폰·Ka VSAT × 하향·상향 프리셋(표 6.1.3.3-1 의 24개 결과와 ±0.1 dB 안에서 같음), 앙각 5~90° 그래프(SNR·경로 손실·거리·도플러·지연), 버짓 표 마크다운·CSV 복사, 지상 링크(거리 직접·log-distance). 브라우저 안에서만 | 누구나 |
| 🕒 시간 변환기 | 지금 유닉스 시간(초·ms) 실시간, 타임스탬프 → 날짜(초·ms·µs·ns 자릿수 자동, ISO·RFC 2822·상대 시간), 날짜+시간대 → 타임스탬프, 세계 시각·서울 기준 시차(도시 추가, 일하는 시간·밤 표시, 서머타임 반영), cron 식 한국어 풀이·다음 실행 5번(@daily·6필드 지원), 날짜 사이 일수·평일 수·D-day·N일/개월/평일 뒤, 기간 변환(5400 ↔ 1시간 30분 ↔ PT1H30M ↔ 01:30:00). 브라우저 안에서만 | 누구나 |
| 🧮 단위 · 진법 변환기 | 진법: 2·8·10·16·직접(2~36) 진수, 0x·0b·0o 자동, 큰 수(BigInt), 8/16/32/64비트 2의 보수·부호 있음/없음, 비트 눌러서 켜고 끄기, 바이트 순서·ASCII, float32/64 로 읽기 + 실수 ↔ IEEE 754. 단위: 아무 칸에 넣으면 나머지가 같이 — 데이터 크기(KB↔KiB)·전송 속도(Mbps↔MB/s, 받는 데 걸리는 시간)·길이·넓이(평)·무게(근·돈)·부피·온도·속도·압력·에너지·전력(dBm↔mW)·dB↔배수·주파수↔파장·각도. 브라우저 안에서만 | 누구나 |
| 🔑 키 생성기 | 길이·문자 종류·형식(Hex, Base64, UUID, PIN, API 키) 비밀번호/키 생성, RSA·ECDSA·Ed25519 키 쌍 PEM·OpenSSH 내보내기. 모두 브라우저 안에서만 생성 | 누구나 |

- 데이터 전송 중계 데몬 `relay/mj_relay.py` (asyncio + pyzmq + aiohttp, systemd 서비스 `mj-relay`) — 라이브 방송(`mj_live.py`)·실시간 게임 방(`mj_game.py`)도 같이 돎, 자세한 내용은 [relay/README.md](relay/README.md)
- 맡겨두기·클립보드 파일은 nginx 가 서빙하지 않는 `private_media/` 에 저장하고, Django 가 권한 확인 후에만 내려줌

### 1.6.1 Game (`/games/`)
상단 메뉴 **Game** (Studio → Settings 에서 다른 메뉴처럼 켜기·끄기·순서·회원 전용). 게임 목록은 `games/registry.py` — `url_name` 이 없으면 '준비 중' 카드.

| 게임 | 설명 |
|---|---|
| 🪜 사다리타기 | 2~12명, 결과 프리셋(당첨 1명·커피 쏘기·순서·청소 당번), 가로줄 양 조절, 결과는 내려가기 전까지 가림, 이름을 누르면 길을 따라 그려 내려감 / 모두 내려가기, 같은 사다리를 링크(#)로 공유 (seed 로 똑같이 다시 만듦) |
| 🎡 돌림판 | 한 줄에 하나 (`치킨 *3` 처럼 비율), 프리셋(점심 메뉴·1~10·벌칙·예/아니오·발표 순서), 딸깍 소리·꽃가루, 당첨 항목 빼고 다음 판, 기록, 링크 공유, 스페이스바로 돌리기 |
| ⏱ 초 맞추기 | '3초를 맞추세요!' 누르는 순간을 0.001초까지 재기(performance.now, 손 떼기 말고 누르는 순간), 타이머 계속 보임 / 1초 뒤 사라짐 / 처음부터 안 보임, 목표 1·3·5·7·10초·🎲 랜덤, 혼자 연습 기록(평균 오차·최고), **🍺 내기 모드**: 여럿이 돌려 가며 한 판, 가까운 순 순위·👑·😱 벌칙 당첨, 판마다 같은 목표, 누적 오차, 카톡용 결과 복사 |
| ⚡ 반응속도 대결 | 빨강 → 초록이 되는 순간 누르기(ms), 먼저 누르면 반칙, 혼자 5번 평균·최고, 내기 모드(제일 느린 사람·반칙 벌칙) |
| 💣 폭탄 돌리기 | 주제(과일·동물·끝말잇기·3·6·9 등)에 맞는 말을 하고 넘기기, 짧게·보통·길게 중 랜덤 시간에 펑, 점점 빨라지는 째깍 소리·진동, 누가 들고 있었는지·벌칙 기록 |
| 🔢 업다운 | 1~50/100/300/1000 숨은 숫자, UP·DOWN 으로 범위 표시, 휴대폰 숫자 키패드, 맞히면 벌칙 / 당첨 |
| 🃏 꽝 뽑기 | 카드 수·꽝 개수 또는 카드마다 직접 적기(벌칙 카드 프리셋), 섞어서 뒤집기 애니메이션, 참가자 차례·뽑은 기록 |
| 💬 공유 | 게임 결과·초대 링크를 카카오톡으로 (`components/share.html`): `KAKAO_JS_KEY` 가 있으면 카카오톡 카드(사진·버튼), 없으면 휴대폰 공유창, 그것도 없으면 복사 |
| 🔢 2048 | 방향키·WASD·밀기, 부드러운 이동·합치기 애니메이션, **서버가 준 seed 로 움직임(U·D·L·R)을 처음부터 다시 둬서 점수 계산**(`games/engine2048.py`, JS 와 같은 난수 mulberry32) → 점수 조작 불가, 한 판은 한 번만 등록 |
| ⌨️ 한글 타자 연습 | 한글(속담·생활 문장)·영어·코딩 문장 10개, 타수는 한컴타자처럼 자모 단위(겹모음·겹받침 2타), 틀린 글자 빨강·조합 중인 글자는 봐줌, 붙여넣기 막음. **문장은 서버가 고르고 채점·시간도 서버 기준**, 정확도 90% 이상·1,500타 이하만 랭킹 |
| 🏆 랭킹 | 로그인 회원만 저장(`games.Score`), 사람마다 최고 기록 하나로 TOP 10 + 내 순위 |
| ⚫ 오목 | 실시간 대국(15×15 자유룰). 회원이 방을 만들고(공개하면 '대기 중인 방' 목록에) 링크를 보내면 받은 사람은 로그인 없이 닉네임만으로 참여, 먼저 앉은 두 명이 흑·백·나머지는 구경. 무르기 부탁(상대 동의)·기권·흑백 바꿔 다시·승수·채팅·돌 소리·마지막 수 표시. 판과 규칙은 mj-relay 의 `relay/mj_game.py` 가 판단, 잠깐 끊겨도 자리 유지 |
| ⚪ 오셀로 | 실시간 8×8 리버시. 오목과 같은 방·자리·무르기·기권·흑백 바꿔 다시 구조에, 상대 돌을 끼운 곳에만 두기(서버가 판단)·둘 수 있는 자리 표시·뒤집히는 애니메이션·돌 개수. 둘 곳이 없으면 자동으로 한 번 쉬고, 둘 다 없으면 돌 많은 쪽 승리 (`OthelloLogic`) |
| 🎨 그림 맞추기 | 실시간(2~10명). 링크로 모이면 방장이 바퀴·시간을 정해 시작, 차례대로 한 명이 제시어 3개 중 하나를 골라 그리고(색 11·굵기 4·되돌리기·다 지우기·넘기기) 나머지는 채팅으로 맞힘. 정답은 채팅에 안 나가고 '정답!' 알림, 빨리 맞힐수록 높은 점수·그린 사람도 점수, 한 글자 차이면 나에게만 '거의 맞았어요', 시간이 지나면 글자 힌트, 중간에 들어와도 지금까지 그림이 보임. 제시어는 직접 만든 320개(`relay/catch_words.py`) |
| 준비 중 | 🖍 그림 ↔ 글 이어하기 (같은 게임 방 위에) |

### 1.7 회원 · 가입 승인
- 회원가입: 아이디, **이름(실명)**, 이메일, 비밀번호, 가입 인사(선택) + **개인정보 수집·이용 동의(필수)**
- 가입 신청 시 계정은 **승인 대기(비활성)** → 관리자가 승인해야 로그인 가능
- 로그인 시 승인 대기 / 거절 / 정지 사유 안내, 안전한 `next` 리다이렉트 검증
- 관리자 로그인 시 Studio 로 이동
- **회원 등급**: 비로그인 < 일반 회원 < **⭐ VIP 회원**(Studio → Users 에서 지정, Django 그룹 `vip`) < 관리자 — `tools/permissions.py` 한 곳에서 관리
  | | AI 기능 (하루 · 한 번 글자 수) | 데이터 전송 방 | 라이브 방송 | 속도 측정 · 포트 체크 |
  |---|---|---|---|---|
  | 일반 회원 | 20번 · 4,000자 | 동시 1 · 하루 3 · 60분 · 8MB/s · 3GB | 동시 1 · 하루 3 · 120분 · 5명 | 기본 한도 |
  | ⭐ VIP 회원 | 100번 · 15,000자 | 동시 3 · 하루 10 · 180분 · 20MB/s · 10GB | 동시 2 · 하루 10 · 240분 · 15명 | 3배 |
  | 관리자 | 제한 없음 | 제한 없음 | 360분 · 20명 | 제한 없음 |
- **✨ AI 기능**(QR 스타일 추천 · 정규식 만들기 · 글 비교 요약 · 네트워크 결과 풀이 · 사진 글자 추출)은 `tools/ai.py` 공통 한도
  - 회원 등급별 하루 횟수·글자 수 + **사이트 전체 하루 예산**(`AI_DAILY_BUDGET_USD`, 넘으면 그날은 관리자 말고 멈춤)
  - Claude 도구 사용(tool_use)으로 정해진 형식만 받고 서버에서 다시 검사, 입력한 글·결과는 저장하지 않고 토큰 수·어림 비용만 기록

### 1.8 관리자 알림
- Logout 옆 **🔔 + 안 읽은 개수** (관리자에게만 표시)
- 알림 종류: 가입 요청, 다른 회원의 댓글 · 방명록 · 새 글 발행 (관리자 본인 활동은 제외)
- `/notifications/`: 종류별 필터, 누르면 읽음 처리 후 해당 화면으로 이동, 모두 읽음 / 읽은 알림 지우기
- **카카오톡 '나에게 보내기'** 연동: 알림 화면에서 카카오톡 연결 → 새 알림을 나와의 채팅으로 전송 (토큰 자동 갱신)

### 1.9 Studio (관리자 전용 CMS, `/studio/`)
- Profile / Career / Activity / Award / Publication / Certification / Skill / Project CRUD, 노출 토글, 순서 변경
- **Posts**: 검색·작성자·기간·**제목 포함(예: 555)** 필터, 발행/임시저장 상태 필터, 공개 범위 변경
  - 일괄 작업(발행, 발행 취소, 공개 범위, 삭제)을 체크한 글 또는 **필터 결과 전체(모든 페이지)** 에 적용
- **Community**: 방명록 · 댓글 검색, 숨기기 / 다시 보이기 / 삭제, 필터 결과 전체 처리
  - 🔗 **단축 링크**: 모든 회원의 단축 링크를 주소·코드·회원으로 검색, 선택/필터 결과 삭제
  - 🧹 **키워드 일괄 정리**: 글 제목·본문, 댓글, 방명록, 단축 링크 주소에서 키워드 포함 항목을 미리보기 후 한 번에 삭제
- **Users**: 회원 검색(아이디·이메일·실명), 승인 대기 / 활성 / ⭐ VIP 회원 / 정지·거절 / 관리자 필터, 글·댓글·방명록 수
  - **⭐ VIP 회원 지정·해제** (줄마다 버튼 또는 일괄)
  - 승인 · 거절 · 정지 · **정지 + 작성한 콘텐츠 전부 삭제** · 계정 삭제 (본인·관리자 계정 제외)
- **Settings**: 상단 메뉴(Home·Blog·Tool·Gallery) 이름·순서·공개 범위(모두 / 로그인 회원만 / 숨김), 홈 화면 섹션 켜기·끄기·순서
  - 숨기거나 회원 전용으로 바꾼 메뉴는 페이지 자체도 막힘 (데이터 전송·맡겨두기·비밀 메모처럼 링크로 여는 페이지는 계속 열림)
- **AI**: 오늘 쓴 돈 / 하루 예산 막대, 오늘·7·30일 호출·토큰·어림 비용(달러·원), 30일 하루 비용 그래프, 기능별·회원별, 최근 호출, 등급별 한도
- **Analytics**: 방문자 통계 (오늘·7·30·90일) — 방문자·페이지뷰, 날짜별 그래프, 인기 글·Tool, 유입 경로(검색·카카오톡·GitHub·SNS)와 들어온 사이트, 기기·시간대
  - IP 미저장(날짜별로 바뀌는 해시로 순방문자만), 봇·링크 미리보기·관리자 본인 방문 제외, 90일 보관
- **Security → 🔎 IP 조회** (`/studio/security/ip/<IP>/`): 보안·로그 화면의 IP 옆 🔎 또는 검색칸. 공개 정보만 — 등록 정보(RDAP: 소유 기관·대역·신고 연락처), ASN·통신사·대략 도시(ipinfo), 열린 포트·태그·알려진 취약점(Shodan InternetDB), Tor 출구, (선택 `ABUSEIPDB_API_KEY`) 신고 점수 — 와 우리 서버 기록(사이트 로그인·시도한 아이디·SSH 실패·nginx 접속 요약·작성 기록·차단). 스캐너·검색 로봇·클라우드·Tor·국내 회선 한 줄 판단, 바로 차단(IP·/24), abuse 신고 메일 초안(로그 포함)·KISA 링크. 상대 IP 로 직접 접속·스캔하지 않음, 결과 하루 캐시
- **Server**: CPU·메모리·디스크, 이번 달 트래픽(재부팅 보정), 서비스(gunicorn·nginx·mj-relay·coturn)·중계 방·예약 작업 상태, 저장 공간
  - 📜 **로그** (`/studio/server/logs/`): 웹 앱(gunicorn·Django 500 traceback)·중계 데몬(mj-relay)·nginx 접속/오류·로그인·SSH(auth.log)·시스템 경고를 읽기 전용으로. 검색(강조)·경고/오류만·최근 200~2000줄·5초 자동 새로고침, nginx 접속은 상태 코드·많이 요청된 주소·IP 요약. 주소의 토큰·초대 코드는 `•••` 로 가림. 서버 계정(ubuntu)이 `adm` 그룹이라 sudo 없이 읽음
  - ⏱ **업타임 모니터**: 웹 주소(HTTP)·포트(TCP)를 1·5·10·30분마다 확인, 2번 연속 실패 시 🔔·카톡 장애 알림, 복구 알림, 24시간·7일 가동률
  - 예약 작업 한 줄(cron, 1분마다): `manage.py run_scheduled` — 업타임 확인, 1시간마다 트래픽 기록, 하루 한 번 보안·통계·맡겨두기·팀플 일정·업타임 기록 정리, S3 백업
  - 💾 **S3 백업**: 마지막 백업 시각·크기·실패 이유, "지금 백업" 버튼, 이틀 넘게 안 되면 경고
- **Security**: 보안 기록과 차단 (기록은 90일 뒤 자동 정리, `python manage.py security_cleanup`)
  - 로그인 기록(성공·실패·잠김), 같은 아이디 15분 5회 / 같은 IP 15분 10회 실패 시 15분 잠금
  - **관리자 계정이 처음 보는 IP 에서 로그인하면 🔔 + 카톡 알림**
  - 글·댓글·방명록 작성 IP·브라우저 기록, IP 로 검색, **증거 CSV 내보내기**
  - IP·대역 차단(기간 지정, 내 IP·너무 넓은 대역은 막지 않음) → 차단된 IP 는 사이트 전체 403
- 삭제 작업은 모두 `DELETE` 확인 문구 입력 필요

---

## 2) 기술 스택

- Python 3.x, **Django 6.0.5**
- PostgreSQL (서버) / SQLite (로컬 기본), boto3 (S3 백업), django-storages (S3 업로드 옵션)
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
├─ blog/              # 블로그/댓글/좋아요/방명록/시리즈, 에디터 렌더링(content.py), 미리보기 카드(og_image.py, fonts/)
├─ main/              # 홈/갤러리/프로젝트 상세, 메타 태그·sitemap·페이지 카드(seo.py, og_cards.py)
├─ studio/            # 관리자 CMS (Posts, Community, Users 포함)
├─ notifications/     # 관리자 알림, 카카오톡 푸시
├─ analytics/         # 방문 기록 미들웨어, 통계 집계
├─ monitor/           # 서버 상태·로그·트래픽·업타임 모니터, S3 백업, 예약 작업(run_scheduled)
├─ security/          # 로그인 기록·잠금, IP 차단 미들웨어, 작성 IP 보관 기간 정리
├─ games/             # Game 메뉴 (사다리타기·돌림판·2048·타자 연습, 랭킹, registry.py 에 게임 목록)
├─ tools/             # Tool 메뉴 (QR·JSON·정규식·키 생성기·네트워크 진단·단축 URL·비밀 메모·클립보드·라이브 방송·데이터 전송 등)
├─ relay/             # 중계 데몬(mj_relay.py: 데이터 전송, mj_live.py: 라이브 방송 시그널링), CLI(mj_stream.py), 설치 스크립트(TURN 포함)
├─ scripts/           # gen_dark_css.py (다크 모드 CSS 생성)
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

# 선택: S3 백업 (USE_S3 와 별개, 버킷에만 권한이 있는 IAM 키)
# BACKUP_S3_BUCKET=...
# BACKUP_AWS_ACCESS_KEY_ID=...
# BACKUP_AWS_SECRET_ACCESS_KEY=...
# BACKUP_S3_REGION=ap-northeast-2
# BACKUP_KEEP_DAYS=30
# BACKUP_HOUR=4

# 선택: 데이터 전송 중계 데몬 (relay/README.md 참고)
# RELAY_API_KEY=...
# RELAY_PORT_MIN=5550
# RELAY_PORT_MAX=5599
# RELAY_PUBLIC_HOST=smjgallery.kr

# 선택: 라이브 방송 TURN 중계 (relay/deploy/install_turn.sh 가 TURN_SECRET 생성)
# TURN_SECRET=...
# TURN_HOST=smjgallery.kr

# 선택: 서버 상태판의 월 데이터 전송 허용량 (GB)
# SERVER_TRANSFER_ALLOWANCE_GB=3072

# 선택: ✨ AI 기능 (Claude API) — QR 스타일 추천 · 정규식 만들기 · 글 비교 요약 · 네트워크 결과 풀이 · 사진 글자 추출
# ANTHROPIC_API_KEY=sk-ant-...
# ANTHROPIC_MODEL=claude-haiku-5-5
# AI_DAILY_BUDGET_USD=1            # 사이트 전체 하루 예산 (0 이면 끔)
# AI_PRICE_INPUT_PER_MTOK=1        # 어림 비용 계산용 단가 (100만 토큰당 달러)
# AI_PRICE_OUTPUT_PER_MTOK=5

# 선택: 논문 인용 도구가 Crossref 에 알려 줄 연락처 (넣으면 더 안정적인 polite pool)
# CROSSREF_MAILTO=you@example.com
# 선택: 깃허브 코드 찾기 — github.com/settings/tokens 에서 권한 없는 fine-grained 토큰 (없으면 검색 분당 10번·README 시간당 60번)
# GITHUB_TOKEN=...
# 선택: 논문 찾기 — OpenAlex 무료 키 (openalex.org 가입, 없으면 서버 전체 하루 검색 약 100번 → 키 있으면 약 1000번)
# OPENALEX_API_KEY=...
# 선택: Studio 보안 IP 조회에 AbuseIPDB 신고 점수 (abuseipdb.com 무료 키)
# ABUSEIPDB_API_KEY=...

# 선택: 검색엔진 소유 확인 (HTML 태그 방식의 content 값만)
# GOOGLE_SITE_VERIFICATION=...
# NAVER_SITE_VERIFICATION=...

# 선택: 카카오톡 공유하기 — 카카오 개발자 콘솔 > 앱 > 앱 키 > JavaScript 키, 플랫폼 > Web 에 https://smjgallery.kr 등록
# KAKAO_JS_KEY=...

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
| `/blog/series/<slug>/` | 시리즈 모아보기 |
| `/blog/feed/`, `/sitemap.xml`, `/robots.txt` | RSS · 사이트맵 · 크롤러 안내 |
| `/s/<코드>` | 단축 URL |
| `/photos/` | Gallery |
| `/games/` | Game 메뉴 (`ladder/`, `roulette/`, `seconds/`, `reaction/`, `bomb/`, `updown/`, `cards/`, `2048/`, `typing/`, `omok/`, `othello/`, `catchmind/`, `scores/<랭킹>/`) |
| `/tools/` | Tool 메뉴 (`qrcode/`, `pdf/`, `image/`, `ocr/`, `gpa/`, `charcount/`, `diff/`, `meet/`, `json/`, `regex/`, `keygen/`, `myip/`, `encode/`, `duplex/`, `subnet/`, `wifi/`, `linkbudget/`, `time/`, `units/`, `cite/`, `papers/`, `stdlib/`, `github/`, `clipboard/`, `speedtest/`, `netcheck/`, `shortlink/`, `secret/`, `live/`, `stream/`, `share/`) |
| `/studio/` | 관리자 CMS (`posts/`, `community/`, `analytics/`, `server/`, `ai/`, `users/`, `security/`, `settings/` 등) |
| `/notifications/` | 관리자 알림 · 카카오톡 연결 |
| `/accounts/signup/`, `/accounts/login/` | 가입 신청 / 로그인 |
| `/admin/` | Django Admin |

---

## 6) 배포

GitHub Actions 워크플로우: [.github/workflows/deploy.yml](.github/workflows/deploy.yml)

- `main` 브랜치 push 시 Lightsail 서버에 SSH 접속해 `deploy.sh` 실행
  - `git pull` → `pip install` → `migrate` → `collectstatic` → gunicorn 재시작 → `mj-relay` 재시작
- 데이터 전송 중계 데몬 최초 설치: `sudo bash relay/deploy/install.sh` + 방화벽 TCP `5550-5599` 개방 ([relay/README.md](relay/README.md))
- 사진 글자 추출(무료)·블로그 수식 OCR 용 Tesseract 설치: `sudo apt-get install -y tesseract-ocr tesseract-ocr-kor`
- 라이브 방송 TURN 서버 최초 설치: `sudo bash relay/deploy/install_turn.sh` + 방화벽 UDP·TCP `3478`, UDP `49160-49200`
- 예약 작업(cron) 1회 등록 — 1분마다 업타임 확인, 1시간마다 트래픽 기록, 하루 한 번 오래된 기록 정리·S3 백업:
  ```
  (crontab -l 2>/dev/null; echo "* * * * * cd /home/ubuntu/projects/smjgallery && venv/bin/python manage.py run_scheduled >/dev/null 2>&1") | crontab -
  ```

---

## 7) 운영 메모

- 관리 명령
  - `python manage.py run_scheduled` — 예약 작업 (위 cron), 업타임·트래픽·정리를 한 번에
  - `python manage.py backup_s3` — 지금 S3 백업 (run_scheduled 가 매일 `BACKUP_HOUR` 시 이후 자동 실행) / `--list` DB 백업 목록 / `--download DIR` 최근 DB + 사진·파일 전부 내려받기
  - `python manage.py security_cleanup` — 90일 지난 로그인 기록·작성 IP 정리 (run_scheduled 가 하루 한 번 실행)
  - `python manage.py cleanup_shared_files` — 만료된 맡겨두기 파일 정리 (업로드·다운로드 때도 자동 정리)
  - `python manage.py clear_guestbook` — 방명록 정리 (평소에는 Studio → Community 사용 권장)
- S3 백업
  - 버킷: `db/날짜_시각.sqlite3.gz`(PostgreSQL 이면 `.pgdump`, `BACKUP_KEEP_DAYS` 일 보관) + `media/`·`private_media/`(바뀐 파일만 올리고, 서버에서 지운 파일도 버킷에는 남김)
  - `.env` 는 비밀키라 백업하지 않음 → 따로 안전하게 보관
  - 복원: `manage.py backup_s3 --download ~/mj-backup` → SQLite 는 `gunzip` 해서 `db.sqlite3` 로, PostgreSQL 은 `pg_restore -d mjgallery 파일.pgdump`, `media/`·`private_media/` 는 프로젝트 폴더로 복사
- DB: 서버는 PostgreSQL 16 (`DB_ENGINE=postgresql`, `django.db.backends.postgresql` 로 적어도 됨). SQLite 에서 옮길 때:
  `dumpdata --natural-foreign --natural-primary -e contenttypes -e auth.permission` → `DB_ENGINE=postgresql manage.py migrate` → `loaddata` → 표마다 행 수 비교 → `.env` 바꾸고 gunicorn 재시작 (옛 `db.sqlite3` 는 되돌리기용으로 남겨둠)
- 새 색을 쓰는 템플릿을 추가하면 `venv/bin/python scripts/gen_dark_css.py` 로 다크 모드 CSS 다시 생성
- 카카오톡은 링크 미리보기를 저장해 두므로, 예전에 보낸 링크는 [카카오 공유 디버거](https://developers.kakao.com/tool/debugger/sharing)에서 캐시 초기화
- 업로드 한도는 `config/settings.py` 의 `DATA_UPLOAD_MAX_MEMORY_SIZE`, `FILE_UPLOAD_MAX_MEMORY_SIZE` (nginx `client_max_body_size` 와 함께 조정)
- 프로덕션에서는 `DEBUG=False`, 안전한 `ALLOWED_HOSTS` 사용, `.env` 는 git 에 올리지 않기
- 회원 개인정보(이름·이메일)는 가입 승인·회원 관리 목적으로만 사용하고, 탈퇴·거절 후 요청 시 삭제

---

## 8) 라이선스

개인 포트폴리오 프로젝트 용도입니다. 필요 시 별도 라이선스를 추가하세요.
