"""Game 허브(/games/) 에 보여줄 게임 목록.

새 게임은 games/urls.py 에 주소, templates/games/ 에 화면, 아래 GAMES 에 한 줄.
url_name 이 None 이면 '준비 중' 카드로만 보임.
"""

CATEGORIES = [
	("party", "🎉", "모임 게임", "여럿이 모였을 때 한 화면으로"),
	("solo", "🕹", "혼자 하기", "기록을 세우고 랭킹에 도전"),
	("versus", "⚔️", "같이 하기", "링크를 보내 실시간으로 같이"),
	("retro", "💾", "추억의 게임관", "옛날 그 느낌"),
]

GAMES = [
	{
		"slug": "ladder",
		"url_name": "games:ladder",
		"icon": "🪜",
		"title": "사다리타기",
		"description": "이름과 결과를 넣으면 사다리가 만들어져요. 이름을 누르면 길을 따라 내려가고, 결과는 마지막까지 가려져 있어요. 링크로 같은 사다리를 공유할 수 있어요.",
		"tags": ["내기", "벌칙"],
		"category": "party",
	},
	{
		"slug": "roulette",
		"url_name": "games:roulette",
		"icon": "🎡",
		"title": "돌림판",
		"description": "점심 메뉴·벌칙·발표 순서를 돌림판으로. 항목마다 비율을 다르게, 당첨된 항목은 빼고 다시 돌리기도 돼요.",
		"tags": ["룰렛", "랜덤"],
		"category": "party",
	},
	{"slug": "2048", "url_name": None, "icon": "🔢", "title": "2048", "description": "같은 숫자를 합쳐 2048 을 만들어요. 랭킹.", "tags": ["퍼즐"], "category": "solo"},
	{"slug": "typing", "url_name": None, "icon": "⌨️", "title": "한글 타자 연습", "description": "문장·속담·코딩 문장으로 타수와 정확도 재기. 랭킹.", "tags": ["타자"], "category": "solo"},
	{"slug": "omok", "url_name": None, "icon": "⚫", "title": "오목", "description": "링크를 보내 친구와 실시간 오목.", "tags": ["1:1"], "category": "versus"},
	{"slug": "catchmind", "url_name": None, "icon": "🎨", "title": "그림 맞추기", "description": "한 명이 그리고 나머지가 맞혀요.", "tags": ["여럿이"], "category": "versus"},
	{"slug": "relay", "url_name": None, "icon": "🖍", "title": "그림 ↔ 글 이어하기", "description": "그림을 보고 글로, 글을 보고 그림으로. 끝에 처음과 비교하면 웃음 폭발.", "tags": ["여럿이"], "category": "versus"},
	{"slug": "bubble", "url_name": None, "icon": "💣", "title": "물풍선 대전", "description": "물풍선으로 길을 막고 터뜨리는 실시간 대전.", "tags": ["대전"], "category": "retro"},
	{"slug": "flash", "url_name": None, "icon": "📼", "title": "플래시 게임관", "description": "올려도 되는 옛날 플래시 게임을 지금 브라우저에서 (Ruffle).", "tags": ["추억"], "category": "retro"},
]
