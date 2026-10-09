"""한글 타자 연습: 문장 모음, 타수(자모 단위) 계산, 채점.

문장은 속담·직접 쓴 연습 문장만 (저작권 있는 글은 넣지 않음).
"""

TEXTS = {
	"ko": [
		"가는 말이 고와야 오는 말이 곱다.", "천 리 길도 한 걸음부터 시작한다.", "백지장도 맞들면 낫다.",
		"낮말은 새가 듣고 밤말은 쥐가 듣는다.", "티끌 모아 태산이 된다.", "세 살 버릇 여든까지 간다.",
		"원숭이도 나무에서 떨어질 때가 있다.", "소 잃고 외양간 고친다.", "등잔 밑이 어둡다.",
		"구슬이 서 말이라도 꿰어야 보배다.", "열 번 찍어 안 넘어가는 나무 없다.", "고생 끝에 낙이 온다.",
		"말 한마디로 천 냥 빚을 갚는다.", "호랑이도 제 말 하면 온다.", "빈 수레가 요란하다.",
		"우물을 파도 한 우물을 파라.", "아니 땐 굴뚝에 연기 날까.", "꿩 먹고 알 먹는다.",
		"돌다리도 두들겨 보고 건너라.", "될성부른 나무는 떡잎부터 알아본다.", "벼는 익을수록 고개를 숙인다.",
		"비 온 뒤에 땅이 굳어진다.", "급할수록 돌아가라.", "웃는 얼굴에 침 못 뱉는다.",
		"하늘이 무너져도 솟아날 구멍이 있다.", "윗물이 맑아야 아랫물이 맑다.", "공든 탑이 무너지랴.",
		"오늘 할 일을 내일로 미루지 말자.", "작은 습관이 모여 큰 변화를 만든다.", "실패는 다시 시작할 기회를 준다.",
		"매일 조금씩 꾸준히 하는 사람이 결국 이긴다.", "모르는 것을 묻는 것은 부끄러운 일이 아니다.",
		"좋은 코드는 읽는 사람을 배려한 코드다.", "백업은 문제가 생기기 전에 해 두어야 한다.",
		"비밀번호는 길고 다른 곳과 겹치지 않게 만들자.", "의심스러운 링크는 누르기 전에 주소를 확인하자.",
		"팀플은 일정과 역할을 먼저 정해야 덜 싸운다.", "발표는 연습한 만큼 떨리지 않는다.",
		"커피 한 잔과 함께 오늘의 할 일을 정리한다.", "주말에는 밀린 빨래와 청소를 끝내야지.",
		"창밖으로 보이는 하늘이 유난히 맑고 푸르다.", "버스를 놓쳐서 다음 차를 기다리는 중이다.",
		"편의점에서 삼각김밥과 바나나우유를 샀다.", "새로 산 키보드는 소리가 경쾌해서 좋다.",
		"서버가 갑자기 멈추면 로그부터 확인하자.", "네트워크가 느릴 때는 핑과 경로를 살펴본다.",
		"햇살 좋은 오후에 공원을 천천히 걸었다.", "따뜻한 국밥 한 그릇이면 하루가 든든하다.",
		"늦었다고 생각할 때가 가장 빠를 때다.", "잘 쉬는 것도 실력이다.",
	],
	"en": [
		"The quick brown fox jumps over the lazy dog.", "Practice makes perfect, so keep typing every day.",
		"Small steps every day lead to big results.", "Always back up your files before you change anything.",
		"A good password is long, unique, and hard to guess.", "Read the error message before you search for answers.",
		"Coffee first, then the bugs will make more sense.", "Simple code is easier to read and easier to fix.",
		"Pack my box with five dozen liquor jugs.", "How vexingly quick daft zebras jump!",
		"Never trust a link you did not expect to receive.", "The network is slow, so let us check the route.",
		"Learning to type fast saves hours every week.", "Write tests so tomorrow you can sleep well.",
		"Every expert was once a beginner who kept going.", "Measure twice and cut once.",
	],
	"code": [
		"for (let i = 0; i < items.length; i++) {", "const total = prices.reduce((a, b) => a + b, 0);",
		"if (user && user.isActive) return true;", "def hello(name):\n", "print(f\"Hello, {name}!\")",
		"import os, sys, json", "SELECT name, email FROM users WHERE active = 1;", "git commit -m \"fix: handle empty list\"",
		"docker compose up -d --build", "ssh -i key.pem ubuntu@example.com", "while True: data = sock.recv(4096)",
		"export const sum = (a, b) => a + b;", "return JsonResponse({\"ok\": True})", "python manage.py migrate",
	],
}
TEXTS["code"] = [t.strip() for t in TEXTS["code"]]
LANGS = {"ko": "한글 문장", "en": "영어 문장", "code": "코딩 문장"}
ROUND = 10  # 한 판 문장 수
MIN_ACCURACY = 90  # 랭킹에 올라가려면
MAX_CPM = 1500  # 사람이 낼 수 있는 속도를 넘으면(자동 입력) 랭킹에 안 올림

# 두벌식에서 겹모음·겹받침은 두 번 누름
_CHO, _JUNG, _JONG = 19, 21, 28
_JUNG_KEYS = [1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 1, 1, 2, 2, 2, 1, 1, 2, 1]  # ㅏ..ㅣ (ㅘㅙㅚ ㅝㅞㅟ ㅢ = 2)
_JONG_KEYS = [0, 1, 1, 2, 1, 2, 2, 1, 1, 2, 2, 2, 2, 2, 2, 2, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1]  # 없음, ㄱ.. (ㄳㄵㄶㄺㄻㄼㄽㄾㄿㅀㅄ = 2)


def keystrokes(text):
	"""한컴타자처럼 타수를 셈: 한글은 자모 단위(겹모음·겹받침 2), 그 밖의 글자는 1."""
	n = 0
	for ch in text:
		code = ord(ch) - 0xAC00
		if 0 <= code < 11172:
			n += 1 + _JUNG_KEYS[(code // _JONG) % _JUNG] + _JONG_KEYS[code % _JONG]
		else:
			n += 1
	return n


def grade(targets, typed, seconds):
	"""문장별로 같은 자리 글자를 비교. 맞힌 글자의 타수 / 분 = 타수(CPM)."""
	correct_keys = total_chars = correct_chars = 0
	for target, got in zip(targets, typed):
		got = (got or "")[: len(target) + 20]
		total_chars += max(len(target), len(got))
		for i, ch in enumerate(target):
			if i < len(got) and got[i] == ch:
				correct_chars += 1
				correct_keys += keystrokes(ch)
	minutes = max(seconds, 1) / 60
	cpm = round(correct_keys / minutes)
	accuracy = round(correct_chars / total_chars * 100, 1) if total_chars else 0
	return {"cpm": cpm, "accuracy": accuracy, "wpm": round(cpm / 5), "seconds": round(seconds, 1)}
