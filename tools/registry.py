"""Tool 허브에 보여줄 도구 목록.

새 도구를 추가할 때는
1. tools/urls.py 에 페이지 URL 추가
2. templates/tools/ 에 템플릿 추가
3. 아래 TOOLS 에 한 줄 추가
하면 허브(/tools/)에 카드가 생긴다.

"access" 로 허브의 칸이 나뉜다 (도구가 하나도 없는 칸은 보이지 않음).
- "public": 누구나
- "member": 회원 전용 (비로그인에게도 보이지만 누르면 로그인 화면으로)
- "admin":  관리자 전용 (관리자에게만 보임)
실제 접근 제한은 각 뷰에서 따로 건다.
"""

SECTIONS = [
	("public", "누구나 쓸 수 있는 도구", "로그인 없이 바로 써요. 계산은 대부분 브라우저 안에서만 이뤄져요."),
	("member", "회원 전용", "서버 자원을 쓰는 도구라 로그인한 회원만 쓸 수 있어요."),
	("admin", "관리자 전용", "사이트 관리자만 보이는 도구예요."),
]

TOOLS = [
	{
		"slug": "keygen",
		"url_name": "tools:keygen",
		"icon": "🔑",
		"title": "암호화 키 생성기",
		"description": "길이·문자 종류·형식(Hex·Base64·UUID·PIN·API 키)을 골라 안전한 키와 비밀번호를 만들고, RSA·ECDSA 키 쌍도 PEM 으로 생성합니다. 모두 브라우저 안에서만 만들어져요.",
		"tags": ["보안", "생성기"],
		"access": "public",
	},
	{
		"slug": "myip",
		"url_name": "tools:myip",
		"icon": "🔍",
		"title": "내 IP · 접속 정보",
		"description": "이 서버가 본 내 공인 IP, IPv4/IPv6, 호스트 이름, 브라우저·OS·화면 정보를 보여주고, 원하면 IP 대역의 통신사·국가도 찾아 줍니다.",
		"tags": ["네트워크", "IP"],
		"access": "public",
	},
	{
		"slug": "encode",
		"url_name": "tools:encode",
		"icon": "🧮",
		"title": "인코딩 · 해시 도구",
		"description": "Base64·URL·Hex·HTML 변환, MD5·SHA 해시와 HMAC, 파일 해시, JWT 내용 보기. 모두 브라우저 안에서만 계산해요.",
		"tags": ["보안", "변환"],
		"access": "public",
	},
	{
		"slug": "clipboard",
		"url_name": "tools:clipboard",
		"icon": "📋",
		"title": "내 클립보드",
		"description": "로그인한 계정에 텍스트·이미지·파일을 붙여넣어 두고, 휴대폰·노트북 등 다른 기기에서 바로 복사하거나 내려받습니다.",
		"tags": ["기기 간 공유"],
		"access": "member",
	},
	{
		"slug": "speedtest",
		"url_name": "tools:speedtest",
		"icon": "⚡",
		"title": "인터넷 속도 측정",
		"description": "지금 내 인터넷으로 이 서버와 실제 데이터를 주고받아 다운로드·업로드 속도와 지연(ping)을 실시간 그래프로 측정합니다.",
		"tags": ["네트워크", "실시간 측정"],
		"access": "member",
	},
	{
		"slug": "duplex",
		"url_name": "tools:duplex",
		"icon": "⇄",
		"title": "Full / Half Duplex 처리량 비교",
		"description": "회선 속도·프레임 크기·방향 전환 시간을 넣으면 전이중과 반이중의 실제 처리량과 전송 시간을 비교해 줍니다.",
		"tags": ["네트워크", "계산기"],
		"access": "public",
	},
	{
		"slug": "subnet",
		"url_name": "tools:subnet",
		"icon": "⌗",
		"title": "IPv4 서브넷 계산기",
		"description": "IP/CIDR 이나 서브넷 마스크를 넣으면 네트워크·브로드캐스트·호스트 범위를 계산하고, 2진수로 보여주고, 더 작은 서브넷으로 나눠 줍니다.",
		"tags": ["네트워크", "계산기"],
		"access": "public",
	},
	{
		"slug": "netcheck",
		"url_name": "tools:netcheck",
		"icon": "📡",
		"title": "포트 · 핑 · DNS 체크",
		"description": "이 서버에서 내 서버로 포트가 열려 있는지, ping 응답 시간, 경로(traceroute), DNS 레코드(A·MX·TXT 등)를 확인합니다.",
		"tags": ["네트워크", "진단"],
		"access": "member",
	},
	{
		"slug": "shortlink",
		"url_name": "tools:shortlink",
		"icon": "🔗",
		"title": "단축 URL",
		"description": "긴 주소를 smjgallery.kr/s/abc123 처럼 짧게 줄이고, 몇 번 열렸는지 확인해요. 유효 기간도 정할 수 있어요.",
		"tags": ["링크", "공유"],
		"access": "member",
	},
	{
		"slug": "secret",
		"url_name": "tools:secret",
		"icon": "🤫",
		"title": "1회용 비밀 메모",
		"description": "비밀번호·키 같은 걸 한 번 열면 사라지는 링크로 전달해요. 브라우저에서 암호화해서 서버는 내용을 알 수 없어요.",
		"tags": ["보안", "공유"],
		"access": "member",
	},
	{
		"slug": "live",
		"url_name": "tools:live",
		"icon": "📺",
		"title": "화면 송출",
		"description": "내 화면·소리, 웹캠·마이크를 링크 받은 사람이 브라우저로 실시간 시청해요. 채팅도 되고, 시청자는 로그인할 필요 없어요.",
		"tags": ["방송", "WebRTC"],
		"access": "member",
	},
	{
		"slug": "stream",
		"url_name": "tools:stream",
		"icon": "📁",
		"title": "데이터 전송",
		"description": "방을 열고 링크를 나눠 주면 브라우저끼리 파일을 바로 주고받아요. 받는 사람이 없으면 맡겨두기, 프로그램 실시간 스트림·GNU Radio(ZMQ) IQ 중계도 지원합니다.",
		"tags": ["파일", "스트리밍"],
		"access": "member",  # 방 만들기는 회원(한도 있음), 받는 쪽은 링크만 있으면 누구나 — tools/permissions.py
	},
]
