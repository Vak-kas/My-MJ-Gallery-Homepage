from django.conf import settings
from django.db import models


class Score(models.Model):
	"""랭킹 기록. 점수는 서버가 직접 계산한 값만 저장 (2048 은 움직임을 다시 둬서, 타자는 입력을 채점해서).
	스도쿠·지뢰찾기는 걸린 시간(ms, 짧을수록 위 — scores.TIME_BOARDS)."""

	BOARDS = [
		("2048", "2048"), ("typing-ko", "타자 · 한글"), ("typing-en", "타자 · 영어"), ("typing-code", "타자 · 코딩"),
		("sudoku-easy", "스도쿠 · 쉬움"), ("sudoku-normal", "스도쿠 · 보통"), ("sudoku-hard", "스도쿠 · 어려움"),
		("mines-easy", "지뢰찾기 · 초급"), ("mines-normal", "지뢰찾기 · 중급"), ("mines-hard", "지뢰찾기 · 고급"),
		("trace-trace", "따라그리기"), ("trace-memory", "따라그리기 · 기억해서"),
	]

	board = models.CharField(max_length=20, choices=BOARDS)
	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="game_scores")
	score = models.IntegerField()
	detail = models.JSONField(default=dict, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-score", "created_at"]
		indexes = [models.Index(fields=["board", "-score"])]

	def __str__(self):
		return f"{self.board} {self.user_id} {self.score}"
