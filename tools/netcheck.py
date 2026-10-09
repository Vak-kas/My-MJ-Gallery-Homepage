"""포트·핑·DNS 체크 (회원 전용).

이 서버에서 다른 호스트로 DNS 조회 / TCP 포트 연결 / ping / 경로 추적을 해 본다.
- 내부 주소(사설·루프백·링크로컬 등)는 막음 → 서버 내부망·클라우드 메타데이터 접근 방지
- 한 번에 포트 10개까지, 회원별 10분에 20회까지 (관리자는 제한 없음)
"""

import ipaddress
import json
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .permissions import quota_multiplier

_pool = ThreadPoolExecutor(max_workers=16)

HOST_RE = re.compile(r"^(?=.{1,253}$)([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")
MAX_PORTS = 10
RUN_LIMIT = 20
RUN_WINDOW = 10 * 60
DOH_URL = "https://cloudflare-dns.com/dns-query"
DNS_TYPES = ["A", "AAAA", "CNAME", "MX", "NS", "TXT"]
COMMON_PORTS = {
	21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS", 80: "HTTP", 110: "POP3", 143: "IMAP",
	443: "HTTPS", 465: "SMTPS", 587: "SMTP 제출", 993: "IMAPS", 995: "POP3S", 3306: "MySQL", 3389: "RDP",
	5432: "PostgreSQL", 6379: "Redis", 8080: "HTTP 대체", 8443: "HTTPS 대체", 27017: "MongoDB",
}


class CheckError(Exception):
	pass


def _error(message, status=400):
	return JsonResponse({"error": message}, status=status)


def _rate_limited(user):
	if user.is_superuser:
		return False
	key = f"netcheck:{user.id}"
	now = time.time()
	bucket = cache.get(key)
	if not bucket or now - bucket["start"] >= RUN_WINDOW:
		bucket = {"start": now, "count": 0}
	if bucket["count"] >= RUN_LIMIT * quota_multiplier(user):
		return True
	bucket["count"] += 1
	cache.set(key, bucket, max(1, int(bucket["start"] + RUN_WINDOW - now)))
	return False


def _clean_host(raw):
	host = (raw or "").strip().lower()
	host = re.sub(r"^[a-z][a-z0-9+.-]*://", "", host).split("/")[0]  # URL 을 붙여넣어도 호스트만
	if host.startswith("[") and "]" in host:
		host = host[1:host.index("]")]
	elif host.count(":") == 1:
		host = host.split(":")[0]  # host:port
	try:
		return str(ipaddress.ip_address(host))
	except ValueError:
		pass
	if not HOST_RE.match(host):
		raise CheckError("호스트 이름이나 IP 주소가 올바르지 않아요.")
	return host


def _resolve(host):
	try:
		infos = _pool.submit(socket.getaddrinfo, host, None, 0, socket.SOCK_STREAM).result(timeout=4)
	except FutureTimeout:
		raise CheckError("DNS 응답이 너무 늦어요.")
	except socket.gaierror:
		raise CheckError("이 이름의 주소를 찾을 수 없어요.")
	addrs = []
	for info in infos:
		ip = info[4][0]
		if ip not in addrs:
			addrs.append(ip)
	return addrs


def _public_target(host):
	"""확인할 대상 IP 하나 (공인 주소만, IPv4 우선)."""
	addrs = _resolve(host)
	public = [a for a in addrs if ipaddress.ip_address(a).is_global]
	if not public:
		raise CheckError("내부·사설 주소는 확인할 수 없어요.")
	public.sort(key=lambda a: ipaddress.ip_address(a).version)
	return public[0], addrs


def _parse_ports(raw):
	ports = []
	for part in re.split(r"[\s,]+", (raw or "").strip()):
		if not part:
			continue
		if "-" in part:
			a, _, b = part.partition("-")
			if not (a.isdigit() and b.isdigit()):
				raise CheckError(f"포트 범위가 올바르지 않아요: {part}")
			ports.extend(range(int(a), int(b) + 1))
		elif part.isdigit():
			ports.append(int(part))
		else:
			raise CheckError(f"포트 번호가 올바르지 않아요: {part}")
	ports = list(dict.fromkeys(ports))
	if not ports:
		raise CheckError("확인할 포트를 입력해 주세요.")
	if len(ports) > MAX_PORTS:
		raise CheckError(f"포트는 한 번에 {MAX_PORTS}개까지 확인할 수 있어요.")
	if any(p < 1 or p > 65535 for p in ports):
		raise CheckError("포트는 1~65535 사이여야 해요.")
	return ports


def _probe(ip, port, timeout=2.5):
	family = socket.AF_INET6 if ":" in ip else socket.AF_INET
	started = time.perf_counter()
	with socket.socket(family, socket.SOCK_STREAM) as s:
		s.settimeout(timeout)
		try:
			s.connect((ip, port))
			return {"port": port, "state": "open", "ms": round((time.perf_counter() - started) * 1000, 1)}
		except ConnectionRefusedError:
			return {"port": port, "state": "closed"}
		except (socket.timeout, TimeoutError):
			return {"port": port, "state": "filtered"}
		except OSError as exc:
			return {"port": port, "state": "error", "detail": exc.strerror or str(exc)}


def check_ports(host, raw_ports):
	ip, _ = _public_target(host)
	ports = _parse_ports(raw_ports)
	results = list(_pool.map(lambda p: _probe(ip, p), ports))
	for r in results:
		r["service"] = COMMON_PORTS.get(r["port"], "")
	return {"target": ip, "ports": results}


def _doh(name, rtype):
	url = DOH_URL + "?" + urllib.parse.urlencode({"name": name, "type": rtype})
	req = urllib.request.Request(url, headers={"Accept": "application/dns-json"})
	with urllib.request.urlopen(req, timeout=5) as res:
		data = json.loads(res.read().decode())
	return [a.get("data", "") for a in data.get("Answer") or [] if a.get("type") == {"A": 1, "AAAA": 28, "CNAME": 5, "MX": 15, "NS": 2, "TXT": 16}[rtype]]


def check_dns(host):
	try:
		ipaddress.ip_address(host)
		is_ip = True
	except ValueError:
		is_ip = False
	result = {"target": host, "records": {}, "reverse": {}}
	if is_ip:
		addrs = [host]
	else:
		def lookup(rtype):
			try:
				return rtype, _doh(host, rtype)
			except (OSError, ValueError, KeyError):
				return rtype, None
		for rtype, values in _pool.map(lookup, DNS_TYPES):
			result["records"][rtype] = values
		addrs = (result["records"].get("A") or []) + (result["records"].get("AAAA") or [])
		if not addrs and all(v is None for v in result["records"].values()):
			addrs = _resolve(host)  # DoH 를 못 쓰면 서버 기본 DNS 로
			result["records"] = {"A/AAAA": addrs}
	def ptr(ip):
		try:
			return ip, _pool.submit(socket.gethostbyaddr, ip).result(timeout=2)[0]
		except (FutureTimeout, OSError):
			return ip, ""
	result["reverse"] = dict(_pool.map(ptr, addrs[:6]))
	return result


def _run(cmd, timeout):
	try:
		proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
		return (proc.stdout or "") + (proc.stderr or "")
	except subprocess.TimeoutExpired as exc:
		out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
		return out + "\n(시간 초과로 중단)"


def check_ping(host):
	ip, _ = _public_target(host)
	binary = shutil.which("ping6" if ":" in ip and sys.platform == "darwin" else "ping")
	if not binary:
		raise CheckError("서버에 ping 명령이 없어요.")
	wait = "2000" if sys.platform == "darwin" else "2"  # macOS 는 ms, Linux 는 초
	output = _run([binary, "-c", "4", "-W", wait, ip], timeout=15)
	summary = {}
	m = re.search(r"(\d+) packets transmitted, (\d+) (?:packets )?received", output)
	if m:
		summary["sent"], summary["received"] = int(m.group(1)), int(m.group(2))
	m = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)", output)
	if m:
		summary["min"], summary["avg"], summary["max"] = (float(x) for x in m.groups())
	return {"target": ip, "summary": summary, "output": output.strip()}


def check_trace(host):
	ip, _ = _public_target(host)
	if shutil.which("tracepath"):
		cmd = ["tracepath", "-n", "-m", "20", ip]
	elif shutil.which("traceroute"):
		cmd = ["traceroute", "-n", "-m", "20", "-w", "1", "-q", "1", ip]
	else:
		raise CheckError("서버에 경로 추적 명령(tracepath/traceroute)이 없어요.")
	return {"target": ip, "output": _run(cmd, timeout=25).strip()}


CHECKS = {
	"dns": lambda data, host: check_dns(host),
	"port": lambda data, host: check_ports(host, data.get("ports")),
	"ping": lambda data, host: check_ping(host),
	"trace": lambda data, host: check_trace(host),
}


@login_required
def netcheck(request):
	return render(request, "tools/netcheck.html", {"max_ports": MAX_PORTS, "run_limit": RUN_LIMIT})


@require_POST
def netcheck_run(request):
	if not request.user.is_authenticated:
		return _error("로그인한 회원만 쓸 수 있어요.", 401)
	try:
		data = json.loads(request.body or b"{}")
	except ValueError:
		return _error("요청 형식이 올바르지 않아요.")
	kind = data.get("type")
	if kind not in CHECKS:
		return _error("확인 종류가 올바르지 않아요.")
	try:
		host = _clean_host(data.get("host"))
		if _rate_limited(request.user):
			return _error(f"10분에 {RUN_LIMIT}번까지 확인할 수 있어요. 잠시 뒤 다시 시도해 주세요.", 429)
		return JsonResponse({"type": kind, "host": host, **CHECKS[kind](data, host)})
	except CheckError as exc:
		return _error(str(exc))
