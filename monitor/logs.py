"""서버 로그 읽기 (Studio > Server > 로그). 읽기만 하고, sudo 없이 ubuntu(adm 그룹) 권한으로 볼 수 있는 것만."""

import os
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

LOG_ROOT = Path(os.environ.get("MJ_LOG_ROOT", "/var/log"))

# key: (이름, 설명, 종류, 대상)
SOURCES = {
    "app": ("웹 앱", "gunicorn · Django 오류(500 traceback)", "journal", ["-u", "gunicorn"]),
    "relay": ("중계 데몬", "mj-relay · 데이터 전송·라이브·게임 방", "journal", ["-u", "mj-relay"]),
    "access": ("nginx 접속", "들어온 요청 전부 (IP·주소·상태 코드)", "file", "nginx/access.log"),
    "nginx_error": ("nginx 오류", "프록시 실패·업로드 크기 초과 등", "file", "nginx/error.log"),
    "auth": ("로그인·SSH", "SSH 접속 시도·sudo 기록", "file", "auth.log"),
    "system": ("시스템 경고", "전체 journal 중 warning 이상", "journal", ["-p", "warning"]),
}
LINE_CHOICES = (200, 500, 1000, 2000)
SCAN_MAX = 20000  # 검색·필터할 때 거슬러 올라가 보는 최대 줄 수
LINE_MAX = 2000  # 한 줄이 너무 길면 자름

ERR = re.compile(r"\b(ERROR|CRITICAL|FATAL|Traceback|Exception|\[(?:error|crit|alert|emerg)\])|(?:^|\s)Error:|failed|Failed", re.I)
WARN = re.compile(r"\b(WARNING|WARN|\[warn\])|refused|timed? ?out|denied", re.I)
# SSH 무작위 대입은 흔한 소음이라 경고로만
NOISE = re.compile(r"Failed password|Invalid user|authentication failure|Connection closed by .*\[preauth\]|Disconnected from .*\[preauth\]")
ACCESS = re.compile(r'^(?P<ip>\S+) \S+ \S+ \[[^\]]+\] "(?P<method>[A-Z]+) (?P<path>\S+)[^"]*" (?P<status>\d{3}) ')
# 주소에 붙은 토큰·초대 코드 등은 가림
SECRET = re.compile(r"([?&](?:token|key|password|passwd|secret|sig|signature|code|t)=)[^&\s\"']+", re.I)


def _tail_file(path, n):
    """파일 끝에서 n 줄. 큰 파일도 뒤에서부터 블록 단위로 읽음."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        data = b""
        while pos > 0 and data.count(b"\n") <= n:
            step = min(64 * 1024, pos)
            pos -= step
            f.seek(pos)
            data = f.read(step) + data
    lines = data.decode("utf-8", "replace").splitlines()
    return lines[-n:]


def _read_file(rel, n):
    path = LOG_ROOT / rel
    if not path.exists():
        return None, f"{path} 가 없어요."
    try:
        lines = _tail_file(path, n)
        # 자정에 로그가 돌아가서 줄이 모자라면 어제 것(.1)도 앞에 붙임
        prev = Path(f"{path}.1")
        if len(lines) < n and prev.exists():
            lines = _tail_file(prev, n - len(lines)) + lines
        return lines, ""
    except PermissionError:
        return None, f"{path} 를 읽을 권한이 없어요. (서버 계정이 adm 그룹인지 확인)"
    except OSError as exc:
        return None, str(exc)


def _read_journal(args, n):
    if not shutil.which("journalctl"):
        return None, "journalctl 이 없는 환경이에요. (서버에서만 보여요)"
    try:
        out = subprocess.run(["journalctl", *args, "-n", str(n), "--no-pager", "-o", "short-iso", "-q"],
                             capture_output=True, text=True, timeout=8, errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"journalctl 실패: {exc}"
    if out.returncode != 0 and not out.stdout:
        return None, (out.stderr or "journalctl 실패").strip()[:300]
    return out.stdout.splitlines(), ""


def level_of(line, source):
    if source == "access":
        m = ACCESS.match(line)
        if m:
            code = int(m["status"])
            return "err" if code >= 500 else "warn" if code >= 400 else ""
    if NOISE.search(line):
        return "warn"
    if ERR.search(line):
        return "err"
    if WARN.search(line):
        return "warn"
    return ""


def access_summary(lines):
    statuses, paths, ips = Counter(), Counter(), Counter()
    for line in lines:
        m = ACCESS.match(line)
        if not m:
            continue
        statuses[m["status"][0] + "xx"] += 1
        paths[SECRET.sub(r"\1•••", m["path"].split("?")[0])[:80]] += 1
        ips[m["ip"]] += 1
    return {
        "total": sum(statuses.values()),
        "status": [(k, statuses.get(k, 0)) for k in ("2xx", "3xx", "4xx", "5xx")],
        "paths": paths.most_common(6),
        "ips": ips.most_common(6),
    }


def read(source, lines=200, q="", level=""):
    """{"lines": [{"text", "level"}], "error", "scanned", "summary"} — 최신이 아래."""
    if source not in SOURCES:
        source = "app"
    _, _, kind, target = SOURCES[source]
    lines = lines if lines in LINE_CHOICES else LINE_CHOICES[0]
    q = (q or "").strip()[:100]
    filtering = bool(q or level in {"err", "warn"})
    want = min(SCAN_MAX, lines * 10) if filtering else lines
    raw, error = (_read_journal(target, want) if kind == "journal" else _read_file(target, want))
    if raw is None:
        return {"source": source, "lines": [], "error": error, "scanned": 0, "summary": None}
    out = []
    needle = q.lower()
    for text in raw:
        text = SECRET.sub(r"\1•••", text[:LINE_MAX])
        lv = level_of(text, source)
        if needle and needle not in text.lower():
            continue
        if level == "err" and lv != "err":
            continue
        if level == "warn" and not lv:
            continue
        out.append({"text": text, "level": lv})
    out = out[-lines:]
    return {
        "source": source,
        "lines": out,
        "error": "",
        "scanned": len(raw),
        "summary": access_summary(r["text"] for r in out) if source == "access" else None,
    }
