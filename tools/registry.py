"""Tool 허브에 보여줄 도구 목록.

새 도구를 추가할 때는
1. tools/urls.py 에 페이지 URL 추가
2. templates/tools/ 에 템플릿 추가
3. 아래 TOOLS 에 한 줄 추가
하면 허브(/tools/)에 카드가 생긴다.
"""

TOOLS = [
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
		"icon": "📡",
		"title": "실시간 데이터 스트림",
		"description": "방(포트)을 열어 두면 HackRF·GNU Radio(ZMQ)나 파일로 보낸 데이터를 받는 쪽이 실시간으로 받습니다. 웹에서 스펙트럼·처리량도 볼 수 있어요.",
		"tags": ["SDR", "관리자"],
		"admin_only": True,  # 권한은 tools/permissions.py 의 can_manage_streams
	},
]
