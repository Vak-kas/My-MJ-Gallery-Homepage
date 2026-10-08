"""Tool 허브에 보여줄 도구 목록.

새 도구를 추가할 때는
1. tools/urls.py 에 페이지 URL 추가
2. templates/tools/ 에 템플릿 추가
3. 아래 TOOLS 에 한 줄 추가
하면 허브(/tools/)에 카드가 생긴다.
"""

TOOLS = [
	{
		"slug": "keygen",
		"url_name": "tools:keygen",
		"icon": "🔑",
		"title": "암호화 키 생성기",
		"description": "길이·문자 종류·형식(Hex·Base64·UUID·PIN·API 키)을 골라 안전한 키와 비밀번호를 만들고, RSA·ECDSA 키 쌍도 PEM 으로 생성합니다. 모두 브라우저 안에서만 만들어져요.",
		"tags": ["보안", "생성기"],
	},
	{
		"slug": "clipboard",
		"url_name": "tools:clipboard",
		"icon": "📋",
		"title": "내 클립보드",
		"description": "로그인한 계정에 텍스트·이미지·파일을 붙여넣어 두고, 휴대폰·노트북 등 다른 기기에서 바로 복사하거나 내려받습니다.",
		"tags": ["기기 간 공유", "로그인"],
		"login_required": True,
	},
	{
		"slug": "speedtest",
		"url_name": "tools:speedtest",
		"icon": "⚡",
		"title": "인터넷 속도 측정",
		"description": "지금 내 인터넷으로 이 서버와 실제 데이터를 주고받아 다운로드·업로드 속도와 지연(ping)을 실시간 그래프로 측정합니다.",
		"tags": ["네트워크", "실시간 측정"],
	},
	{
		"slug": "duplex",
		"url_name": "tools:duplex",
		"icon": "⇄",
		"title": "Full / Half Duplex 처리량 비교",
		"description": "회선 속도·프레임 크기·방향 전환 시간을 넣으면 전이중과 반이중의 실제 처리량과 전송 시간을 비교해 줍니다.",
		"tags": ["네트워크", "계산기"],
	},
	{
		"slug": "subnet",
		"url_name": "tools:subnet",
		"icon": "⌗",
		"title": "IPv4 서브넷 계산기",
		"description": "IP/CIDR 이나 서브넷 마스크를 넣으면 네트워크·브로드캐스트·호스트 범위를 계산하고, 2진수로 보여주고, 더 작은 서브넷으로 나눠 줍니다.",
		"tags": ["네트워크", "계산기"],
	},
	{
		"slug": "stream",
		"url_name": "tools:stream",
		"icon": "📁",
		"title": "데이터 전송",
		"description": "방을 열고 링크를 나눠 주면 브라우저끼리 파일을 바로 주고받아요. 받는 사람이 없으면 맡겨두기, 프로그램 실시간 스트림·GNU Radio(ZMQ) IQ 중계도 지원합니다.",
		"tags": ["파일", "스트리밍", "관리자"],
		"admin_only": True,  # 권한은 tools/permissions.py 의 can_manage_streams
	},
]
