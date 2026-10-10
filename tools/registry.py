"""Tool 허브에 보여줄 도구 목록.

새 도구를 추가할 때는
1. tools/urls.py 에 페이지 URL 추가
2. templates/tools/ 에 템플릿 추가
3. 아래 TOOLS 에 한 줄 추가
하면 허브(/tools/)에 카드가 생긴다.

"category" 로 허브의 칸이 나뉜다 (CATEGORIES 의 key, 도구가 하나도 없는 칸은 보이지 않음).

"added" 는 처음 만든 때 (Tool 목록의 '새로 나온 순'·🆕 표시).

"access" 는 누가 쓸 수 있는지:
- "public": 누구나
- "member": 회원 전용 (비로그인에게도 보이지만 🔒 금색 테두리, 누르면 로그인 화면으로)
- "vip":    VIP 회원 전용 (누구에게나 보이지만 💎 무지개 테두리)
- "admin":  관리자 전용 (관리자에게만 보이고, 분류와 상관없이 맨 아래 "관리자 전용" 칸에 모임)
실제 접근 제한은 각 뷰에서 따로 건다.
"""

CATEGORIES = [
	("docs", "📝", "문서 · 공부", "자소서·과제·PDF·학점, 공부할 때 쓰는 도구"),
	("share", "🔗", "공유 · 전송", "파일·글·화면을 다른 사람이나 내 다른 기기로"),
	("network", "🌐", "네트워크", "내 인터넷과 서버 상태 확인, 네트워크 계산기"),
	("dev", "🛠", "개발 · 보안", "데이터 변환, 정규식, 해시와 키 만들기"),
]

TOOLS = [
	{
		"slug": "charcount",
		"url_name": "tools:charcount",
		"icon": "✍️",
		"title": "글자 수 세기",
		"description": "자소서·과제 글자 수를 공백 포함·제외, 바이트, 원고지 매수로 세고, 목표 글자 수까지 얼마 남았는지·많이 쓴 단어·너무 긴 문장을 알려줘요.",
		"tags": ["자소서", "글쓰기"],
		"category": "docs",
		"added": "2026-10-09T15:26",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
	{
		"slug": "diff",
		"url_name": "tools:textdiff",
		"icon": "🔀",
		"title": "글 비교",
		"description": "두 글에서 바뀐 부분을 색으로 보여줘요. 줄·단어·글자 단위, 나란히 보기, 공백 무시. 자소서 수정본·계약서 비교에 좋아요.",
		"tags": ["문서", "비교"],
		"category": "docs",
		"added": "2026-10-09T15:26",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
	{
		"slug": "pdf",
		"url_name": "tools:pdf",
		"icon": "📄",
		"title": "PDF 도구",
		"description": "PDF 합치기·나누기, 페이지 빼기·돌리기·순서 바꾸기, 사진 여러 장을 PDF 하나로. 파일이 서버로 가지 않고 브라우저 안에서만 처리돼요.",
		"tags": ["문서", "PDF"],
		"category": "docs",
		"added": "2026-10-09T15:19",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
	{
		"slug": "image",
		"url_name": "tools:image",
		"icon": "🖼",
		"title": "이미지 도구",
		"description": "사진 용량 줄이기(“5MB 이하로”), 크기·형식 바꾸기(HEIC → JPG, PNG ↔ WebP), 자르기·돌리기, 위치정보 지우기. 여러 장을 한꺼번에 ZIP 으로 받아요. 브라우저 안에서만 처리돼요.",
		"tags": ["사진", "변환"],
		"category": "docs",
		"added": "2026-10-09T16:57",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
	{
		"slug": "ocr",
		"url_name": "tools:ocr",
		"icon": "📷",
		"title": "사진 글자 추출",
		"description": "사진·캡처·문서 속 글자를 뽑아 바로 복사해요. 기본은 무료로 읽고, 손글씨·칠판·표는 ✨AI 로 다시 읽으면 훨씬 정확해요(회원). 여러 장, ⌘V 붙여넣기.",
		"tags": ["OCR", "AI"],
		"category": "docs",
		"added": "2026-10-09T20:05",  # 처음 만든 때 (새로 나온 순)
		"access": "public",  # 무료 읽기는 누구나, AI 읽기는 회원
	},
	{
		"slug": "stdlib",
		"url_name": "tools:stdlib",
		"icon": "📖",
		"title": "표준 서재",
		"description": "갖고 있는 표준 PDF(IEEE 802.11be·ax, 3GPP 등)를 올리면 절 단위로 나눠서 'puncturing pattern'·'펑처링'처럼 찾고, 원문 쪽을 그림으로 보고, ✨AI 에게 절·쪽 근거를 붙여 물어봐요. 내 문서는 나만 봐요.",
		"tags": ["표준", "802.11"],
		"category": "docs",
		"added": "2026-10-10T03:01",  # 처음 만든 때 (새로 나온 순)
		"access": "vip",
	},
	{
		"slug": "papers",
		"url_name": "tools:papers",
		"icon": "📑",
		"title": "논문 찾기",
		"description": "키워드(NTN jamming 처럼)로 논문 검색 — 통신 약어는 알아서 넓혀 찾고, 인용순·최신순·저널/학회·기간으로 거르기. 참고문헌·인용한 논문 꼬리 물기, 바로 인용, 내 논문함(회원).",
		"tags": ["논문", "검색"],
		"category": "docs",
		"added": "2026-10-10T01:44",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
	{
		"slug": "cite",
		"url_name": "tools:cite",
		"icon": "📚",
		"title": "논문 인용 만들기",
		"description": "DOI·arXiv 번호·논문 제목·3GPP 규격 번호(TS 38.321)를 넣으면 BibTeX·APA·IEEE·MLA·Chicago 인용을 바로. 갖고 있는 BibTeX 변환, 참고문헌 목록·.bib 저장.",
		"tags": ["논문", "BibTeX"],
		"category": "docs",
		"added": "2026-10-10T00:53",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
	{
		"slug": "diagram",
		"url_name": "tools:diagram",
		"icon": "📊",
		"title": "다이어그램 그리기",
		"description": "글(Mermaid)로 흐름도·순서도(프로토콜 절차)·상태도·ER·간트·마인드맵을 바로 그려요. SVG·PNG 저장, 링크로 공유, ✨말로 그리기·오류 고치기(회원).",
		"tags": ["그림", "Mermaid"],
		"category": "docs",
		"added": "2026-10-10T22:48",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
	{
		"slug": "gpa",
		"url_name": "tools:gpa",
		"icon": "🎓",
		"title": "학점 계산기",
		"description": "과목별·학기별 평점과 전공 평점, 4.5 ↔ 4.3 ↔ 100점 환산, 목표 학점까지 앞으로 몇 점이 필요한지 계산해요. 성적은 이 브라우저에만 저장돼요.",
		"tags": ["대학생", "계산기"],
		"category": "docs",
		"added": "2026-10-09T16:50",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
	{
		"slug": "stream",
		"url_name": "tools:stream",
		"icon": "📁",
		"title": "데이터 전송",
		"description": "방을 열고 링크를 나눠 주면 브라우저끼리 파일을 바로 주고받아요. 받는 사람이 없으면 맡겨두기, 프로그램 실시간 스트림·GNU Radio(ZMQ) IQ 중계도 지원합니다.",
		"tags": ["파일", "스트리밍"],
		"category": "share",
		"added": "2026-10-07T20:53",  # 처음 만든 때 (새로 나온 순)
		"access": "member",  # 방 만들기는 회원(한도 있음), 받는 쪽은 링크만 있으면 누구나 — tools/permissions.py
	},
	{
		"slug": "meet",
		"url_name": "tools:meet",
		"icon": "📅",
		"title": "팀플 일정 맞추기",
		"description": "날짜와 시간대를 정해 링크를 돌리면, 각자 되는 시간을 드래그로 칠해요. 겹치는 시간이 진하게 보이고 '모두 되는 시간'을 바로 찾아줘요. 참여는 로그인 없이.",
		"tags": ["팀플", "약속"],
		"category": "share",
		"added": "2026-10-09T17:11",  # 처음 만든 때 (새로 나온 순)
		"access": "member",  # 만들기는 회원, 링크로 참여는 누구나
	},
	{
		"slug": "clipboard",
		"url_name": "tools:clipboard",
		"icon": "📋",
		"title": "내 클립보드",
		"description": "로그인한 계정에 텍스트·이미지·파일을 붙여넣어 두고, 휴대폰·노트북 등 다른 기기에서 바로 복사하거나 내려받습니다.",
		"tags": ["기기 간 공유"],
		"category": "share",
		"added": "2026-10-08T09:35",  # 처음 만든 때 (새로 나온 순)
		"access": "member",
	},
	{
		"slug": "shortlink",
		"url_name": "tools:shortlink",
		"icon": "🔗",
		"title": "단축 URL",
		"description": "긴 주소를 smjgallery.kr/s/abc123 처럼 짧게 줄이고, 몇 번 열렸는지 확인해요. 유효 기간도 정할 수 있어요.",
		"tags": ["링크", "공유"],
		"category": "share",
		"added": "2026-10-09T02:39",  # 처음 만든 때 (새로 나온 순)
		"access": "member",
	},
	{
		"slug": "paste",
		"url_name": "tools:paste",
		"icon": "📋",
		"title": "코드 붙여넣기 공유",
		"description": "코드·로그·설정 파일을 붙여 넣으면 색칠된 링크가 생겨요. 줄 번호 눌러 그 줄만 가리키기, 원본·내려받기, 고쳐서 새로 만들기. 카톡에 코드가 깨지지 않아요.",
		"tags": ["코드", "공유"],
		"category": "share",
		"added": "2026-10-10T23:02",  # 처음 만든 때 (새로 나온 순)
		"access": "member",
	},
	{
		"slug": "secret",
		"url_name": "tools:secret",
		"icon": "🤫",
		"title": "1회용 비밀 메모",
		"description": "비밀번호·키 같은 걸 한 번 열면 사라지는 링크로 전달해요. 브라우저에서 암호화해서 서버는 내용을 알 수 없어요.",
		"tags": ["보안", "공유"],
		"category": "share",
		"added": "2026-10-09T02:39",  # 처음 만든 때 (새로 나온 순)
		"access": "member",
	},
	{
		"slug": "qrcode",
		"url_name": "tools:qrcode",
		"icon": "▦",
		"title": "QR 코드 만들기",
		"description": "주소·글·Wi-Fi·연락처·문자·메일을 QR 코드로 만들어요. 색·모양·가운데 로고를 바꾸고 PNG·SVG 로 저장, 사진 속 QR 읽기도 돼요.",
		"tags": ["생성기", "공유"],
		"category": "share",
		"added": "2026-10-09T05:11",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
	{
		"slug": "live",
		"url_name": "tools:live",
		"icon": "📺",
		"title": "라이브 방송",
		"description": "화면·웹캠·마이크로 실시간 방송하고, 링크 받은 사람은 로그인 없이 보며 채팅해요. 직접 연결이 막힌 네트워크는 서버가 중계해요.",
		"tags": ["방송", "WebRTC"],
		"category": "share",
		"added": "2026-10-09T04:17",  # 처음 만든 때 (새로 나온 순)
		"access": "member",
	},
	{
		"slug": "myip",
		"url_name": "tools:myip",
		"icon": "🔍",
		"title": "내 IP · 접속 정보",
		"description": "이 서버가 본 내 공인 IP, IPv4/IPv6, 호스트 이름, 브라우저·OS·화면 정보를 보여주고, 원하면 IP 대역의 통신사·국가도 찾아 줍니다.",
		"tags": ["네트워크", "IP"],
		"category": "network",
		"added": "2026-10-09T02:32",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
	{
		"slug": "speedtest",
		"url_name": "tools:speedtest",
		"icon": "⚡",
		"title": "인터넷 속도 측정",
		"description": "지금 내 인터넷으로 이 서버와 실제 데이터를 주고받아 다운로드·업로드 속도와 지연(ping)을 실시간 그래프로 측정합니다.",
		"tags": ["네트워크", "실시간 측정"],
		"category": "network",
		"added": "2026-10-07T08:47",  # 처음 만든 때 (새로 나온 순)
		"access": "member",
	},
	{
		"slug": "netcheck",
		"url_name": "tools:netcheck",
		"icon": "📡",
		"title": "포트 · 핑 · DNS 체크",
		"description": "이 서버에서 내 서버로 포트가 열려 있는지, ping 응답 시간, 경로(traceroute), DNS 레코드(A·MX·TXT 등)를 확인합니다.",
		"tags": ["네트워크", "진단"],
		"category": "network",
		"added": "2026-10-09T02:35",  # 처음 만든 때 (새로 나온 순)
		"access": "member",
	},
	{
		"slug": "wifi",
		"url_name": "tools:wifi",
		"icon": "📶",
		"title": "Wi‑Fi 계산기",
		"description": "Wi‑Fi 4·5·6·7(802.11n/ac/ax/be) 속도(대역폭·MCS·스트림·GI), 거리·벽으로 신호 세기와 예상 속도, 2.4·5·6 GHz 채널 겹침과 추천.",
		"tags": ["Wi‑Fi", "계산기"],
		"category": "network",
		"added": "2026-10-10T02:37",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
	{
		"slug": "satellite",
		"url_name": "tools:satellite",
		"icon": "🛰",
		"title": "위성 궤도 · NTN 계산기",
		"description": "고도만 넣으면 공전 주기·왕복 지연(투명/재생)·도플러·경로 손실·덮는 범위. 실제 위성(ISS·스타링크·GPS)이 지금 어디 있고 언제 내 위로 지나가는지, 궤도·3GPP NTN·재밍 개념 정리까지.",
		"tags": ["위성", "NTN"],
		"category": "network",
		"added": "2026-10-11T00:46",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
	{
		"slug": "linkbudget",
		"url_name": "tools:linkbudget",
		"icon": "📡",
		"title": "링크 버짓 계산기 (위성·NTN)",
		"description": "궤도·앙각·주파수로 거리·경로 손실·C/N0·SNR·용량·도플러·지연을 계산. 3GPP TR 38.821 Set-1/2 (GEO·LEO-1200·LEO-600, S 대역 휴대폰·Ka VSAT) 프리셋, 앙각별 그래프, 버짓 표 복사.",
		"tags": ["NTN", "계산기"],
		"category": "network",
		"added": "2026-10-10T02:26",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
	{
		"slug": "subnet",
		"url_name": "tools:subnet",
		"icon": "⌗",
		"title": "IPv4 서브넷 계산기",
		"description": "IP/CIDR 이나 서브넷 마스크를 넣으면 네트워크·브로드캐스트·호스트 범위를 계산하고, 2진수로 보여주고, 더 작은 서브넷으로 나눠 줍니다.",
		"tags": ["네트워크", "계산기"],
		"category": "network",
		"added": "2026-10-07T00:30",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
	{
		"slug": "duplex",
		"url_name": "tools:duplex",
		"icon": "⇄",
		"title": "Full / Half Duplex 처리량 비교",
		"description": "회선 속도·프레임 크기·방향 전환 시간을 넣으면 전이중과 반이중의 실제 처리량과 전송 시간을 비교해 줍니다.",
		"tags": ["네트워크", "계산기"],
		"category": "network",
		"added": "2026-10-07T00:09",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
	{
		"slug": "github",
		"url_name": "tools:github",
		"icon": "💻",
		"title": "깃허브 코드 찾기",
		"description": "'이런 거 누가 만들어 놨을 텐데' 싶을 때 — 아이디어를 한국어로 쓰면 ✨AI 가 검색어로 바꿔 찾고, 별·언어·라이선스(가져다 써도 되는지)·README 를 보고, 내 아이디어와 맞는지 평가. 논문 코드도.",
		"tags": ["깃허브", "오픈소스"],
		"category": "dev",
		"added": "2026-10-10T11:46",  # 처음 만든 때 (새로 나온 순)
		"access": "member",
	},
	{
		"slug": "json",
		"url_name": "tools:json",
		"icon": "{ }",
		"title": "JSON 정리",
		"description": "JSON 을 보기 좋게 정리하거나 한 줄로 줄이고, 오류 위치를 짚어 주고, 접고 펼치는 트리로 보여줘요. 키 정렬·CSV 변환도 돼요.",
		"tags": ["개발", "변환"],
		"category": "dev",
		"added": "2026-10-09T13:28",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
	{
		"slug": "time",
		"url_name": "tools:time",
		"icon": "🕒",
		"title": "시간 변환기",
		"description": "유닉스 타임스탬프 ↔ 날짜, 세계 시각·시차, cron 식 한국어 풀이와 다음 실행 시각, 날짜 사이 일수·D-day, 기간(PT1H30M ↔ 1시간 30분) 변환.",
		"tags": ["타임스탬프", "cron"],
		"category": "dev",
		"added": "2026-10-10T00:58",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
	{
		"slug": "units",
		"url_name": "tools:units",
		"icon": "🧮",
		"title": "단위 · 진법 변환기",
		"description": "2·8·10·16진법(큰 수·2의 보수·비트 켜고 끄기·IEEE 754), 데이터 크기·전송 속도, 평↔m², dBm↔mW, 주파수↔파장, 온도·길이·무게 등 한 번에 변환.",
		"tags": ["진법", "단위"],
		"category": "dev",
		"added": "2026-10-10T01:05",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
	{
		"slug": "webhook",
		"url_name": "tools:webhook",
		"icon": "🪝",
		"title": "웹훅 · 요청 확인기",
		"description": "나만의 주소를 만들어 깃허브·결제·IoT 기기·내 코드가 보내는 요청(방식·헤더·본문)을 실시간으로 봐요. JSON 보기 좋게, curl 로 복사, 서명(HMAC) 확인, 돌려줄 답 정하기.",
		"tags": ["개발", "API"],
		"category": "dev",
		"added": "2026-10-11T00:19",  # 처음 만든 때 (새로 나온 순)
		"access": "member",
	},
	{
		"slug": "regex",
		"url_name": "tools:regex",
		"icon": ".*",
		"title": "정규식 테스트",
		"description": "정규식을 입력하면 맞는 부분을 바로 칠해 주고, 그룹·치환 결과와 패턴 설명을 보여줘요. 자주 쓰는 패턴 모음도 있어요.",
		"tags": ["개발", "텍스트"],
		"category": "dev",
		"added": "2026-10-09T13:28",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
	{
		"slug": "encode",
		"url_name": "tools:encode",
		"icon": "🧮",
		"title": "인코딩 · 해시 도구",
		"description": "Base64·URL·Hex·HTML 변환, MD5·SHA 해시와 HMAC, 파일 해시, JWT 내용 보기. 모두 브라우저 안에서만 계산해요.",
		"tags": ["보안", "변환"],
		"category": "dev",
		"added": "2026-10-09T02:32",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
	{
		"slug": "keygen",
		"url_name": "tools:keygen",
		"icon": "🔑",
		"title": "암호화 키 생성기",
		"description": "길이·문자 종류·형식(Hex·Base64·UUID·PIN·API 키)을 골라 안전한 키와 비밀번호를 만들고, RSA·ECDSA 키 쌍도 PEM 으로 생성합니다. 모두 브라우저 안에서만 만들어져요.",
		"tags": ["보안", "생성기"],
		"category": "dev",
		"added": "2026-10-08T11:38",  # 처음 만든 때 (새로 나온 순)
		"access": "public",
	},
]
