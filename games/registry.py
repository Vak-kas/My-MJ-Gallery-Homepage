"""Game 허브(/games/) 에 보여줄 게임 목록.

새 게임은 games/urls.py 에 주소, templates/games/ 에 화면, 아래 GAMES 에 한 줄.
url_name 이 None 이면 '준비 중' 카드로만 보임.
"""

CATEGORIES = [
	("party", "🎉", "모임 게임", "여럿이 모였을 때 한 화면으로"),
	("solo", "🕹", "혼자 하기", "기록을 세우고 랭킹에 도전"),
	("versus", "⚔️", "같이 하기", "링크를 보내 실시간으로 같이"),
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
	{
		"slug": "seconds",
		"url_name": "games:seconds",
		"icon": "⏱",
		"title": "초 맞추기",
		"description": "'3초를 맞추세요!' 감으로 멈춰서 0.001초까지 비교해요. 타이머가 사라지는 모드, 랜덤 목표, 여럿이 돌려 가며 하는 내기 모드(꼴찌 벌칙).",
		"tags": ["내기", "반응"],
		"category": "party",
	},
	{
		"slug": "reaction",
		"url_name": "games:reaction",
		"icon": "⚡",
		"title": "반응속도 대결",
		"description": "빨간 화면이 초록으로 바뀌는 순간 누르기. 먼저 누르면 반칙! 혼자 5번 평균, 여럿이 돌려 가며 하면 제일 느린 사람이 벌칙.",
		"tags": ["내기", "반응"],
		"category": "party",
	},
	{
		"slug": "bomb",
		"url_name": "games:bomb",
		"icon": "💣",
		"title": "폭탄 돌리기",
		"description": "주제에 맞는 단어를 말하고 폰을 넘기기. 랜덤 시간에 ‘펑!’ 하고 터지면 들고 있던 사람이 벌칙. 째깍 소리·진동.",
		"tags": ["내기", "술자리"],
		"category": "party",
	},
	{
		"slug": "updown",
		"url_name": "games:updown",
		"icon": "🔢",
		"title": "업다운",
		"description": "숨은 숫자를 돌아가며 불러요. UP·DOWN 으로 좁혀지고, 맞히는 사람이 벌칙(또는 당첨).",
		"tags": ["내기", "숫자"],
		"category": "party",
	},
	{
		"slug": "cards",
		"url_name": "games:cards",
		"icon": "🃏",
		"title": "꽝 뽑기",
		"description": "카드를 섞어 뒤집어 두고 한 장씩. 꽝 개수를 정하거나 벌칙 카드를 직접 적어서. 누가 뭘 뽑았는지 기록.",
		"tags": ["내기", "제비뽑기"],
		"category": "party",
	},
	{
		"slug": "2048",
		"url_name": "games:2048",
		"icon": "🔢",
		"title": "2048",
		"description": "같은 숫자를 밀어 합쳐서 2048 을 만들어요. 방향키·WASD·밀기(휴대폰). 점수는 서버가 직접 다시 둬서 계산하는 랭킹.",
		"tags": ["퍼즐", "랭킹"],
		"category": "solo",
	},
	{
		"slug": "typing",
		"url_name": "games:typing",
		"icon": "⌨️",
		"title": "한글 타자 연습",
		"description": "속담·생활 문장 10개를 쳐서 타수(한컴타자처럼 자모 단위)와 정확도를 재요. 영어·코딩 문장도. 정확도 90% 이상이면 랭킹 등록.",
		"tags": ["타자", "랭킹"],
		"category": "solo",
	},
	{
		"slug": "omok",
		"url_name": "games:omok",
		"icon": "⚫",
		"title": "오목",
		"description": "방을 만들어 링크를 보내면 친구와 실시간 대국. 받은 사람은 로그인 없이 닉네임만. 구경·채팅·무르기·흑백 바꿔 다시 하기.",
		"tags": ["1:1", "실시간"],
		"category": "versus",
	},
	{"slug": "wordchain", "url_name": None, "icon": "🔤", "title": "끝말잇기", "description": "끄투처럼 실시간 끝말잇기. 사전에 있는 단어만, 두음법칙, 시간 제한.", "tags": ["여럿이", "실시간"], "category": "versus"},
	{"slug": "catchmind", "url_name": None, "icon": "🎨", "title": "그림 맞추기", "description": "한 명이 그리고 나머지가 맞혀요.", "tags": ["여럿이"], "category": "versus"},
	{"slug": "relay", "url_name": None, "icon": "🖍", "title": "그림 ↔ 글 이어하기", "description": "그림을 보고 글로, 글을 보고 그림으로. 끝에 처음과 비교하면 웃음 폭발.", "tags": ["여럿이"], "category": "versus"},
]
