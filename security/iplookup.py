"""Studio 보안 — IP 한 개 조회 (관리자만).

공개된 정보만 모음. 상대 IP 로 포트 스캔·접속 같은 '능동적인' 확인은 하지 않음(정보통신망법상 문제 소지).
- 등록 정보(RDAP): 소유 기관·대역·국가·신고(abuse) 연락처
- ipinfo.io: ASN·통신사, 대략적인 도시(통신사 장비 위치 기준, 사람 위치 아님)
- Shodan InternetDB: 이미 공개적으로 수집된 열린 포트·태그(cloud·vpn…)·알려진 취약점 — 키 필요 없음
- Tor 출구 노드 목록, (선택) AbuseIPDB 신고 점수 — ABUSEIPDB_API_KEY 가 있을 때만
- 우리 서버 기록: 로그인 시도·작성 기록·차단·nginx 접속·SSH(auth.log)
"""

import ipaddress
import json
import re
import socket
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count

UA = "MjGallery-Security/1.0 (https://smjgallery.kr)"
CACHE_SECONDS = 24 * 60 * 60
_pool = ThreadPoolExecutor(max_workers=6)

# 인터넷 전체를 훑는 연구·보안 회사, 검색엔진 (역방향 DNS·기관 이름으로 판단)
KNOWN = [
	(r"censys", "Censys (인터넷 전체 스캔 연구 회사)", "scanner"),
	(r"shodan", "Shodan (인터넷 기기 검색 서비스)", "scanner"),
	(r"shadowserver", "Shadowserver (비영리 보안 감시 단체)", "scanner"),
	(r"binaryedge", "BinaryEdge (인터넷 스캔 서비스)", "scanner"),
	(r"stretchoid", "Stretchoid (인터넷 스캔)", "scanner"),
	(r"internet-?measurement|driftnet", "Internet Measurement (인터넷 스캔 연구)", "scanner"),
	(r"onyphe", "ONYPHE (인터넷 스캔 서비스)", "scanner"),
	(r"criminalip|aispera", "Criminal IP (인터넷 스캔 서비스)", "scanner"),
	(r"leakix", "LeakIX (인터넷 스캔 서비스)", "scanner"),
	(r"rapid7|project ?sonar", "Rapid7 Project Sonar (보안 연구 스캔)", "scanner"),
	(r"palo ?alto|xpanse|expanse", "Palo Alto Xpanse (공격 표면 스캔)", "scanner"),
	(r"recyber|alphastrike|netsystemsresearch|ipip\.net", "인터넷 스캔 연구", "scanner"),
	(r"googlebot\.com|google\.com$", "Google (검색 로봇일 수 있음)", "bot"),
	(r"search\.msn\.com", "Bing 검색 로봇", "bot"),
	(r"naver\.com$|yeti", "네이버 검색 로봇", "bot"),
	(r"applebot", "Apple 검색 로봇", "bot"),
]
CLOUD = re.compile(r"amazon|aws|google cloud|google llc|microsoft|azure|digitalocean|linode|akamai|vultr|ovh|hetzner|oracle|alibaba|tencent|choopa|contabo|scaleway|naver cloud|kt cloud|leaseweb|m247|datacamp", re.I)


def parse(raw):
	try:
		return ipaddress.ip_address((raw or "").strip())
	except ValueError:
		return None


def _get_json(url, headers=None, timeout=6):
	req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
	with urllib.request.urlopen(req, timeout=timeout) as res:
		return json.loads(res.read().decode("utf-8", "replace"))


def _vcard(entity, key):
	return [i[3] for i in (entity.get("vcardArray") or [None, []])[1] if i and i[0] == key]


def rdap(ip):
	data = _get_json(f"https://rdap.org/ip/{ip}", {"Accept": "application/rdap+json"}, timeout=8)
	orgs, abuse, contacts = [], [], []

	def walk(ents):
		for e in ents or []:
			roles = e.get("roles") or []
			name = next(iter(_vcard(e, "fn")), "")
			if name and "registrant" in roles and name not in orgs:
				orgs.append(name)
			for mail in _vcard(e, "email"):
				if "abuse" in roles and mail not in abuse:
					abuse.append(mail)
				elif ("technical" in roles or "administrative" in roles or "noc" in roles) and mail not in contacts:
					contacts.append(mail)
			walk(e.get("entities"))

	walk(data.get("entities"))
	cidr = ", ".join(f"{c.get('v4prefix') or c.get('v6prefix')}/{c.get('length')}" for c in (data.get("cidr0_cidrs") or [])[:4])
	events = {e.get("eventAction"): (e.get("eventDate") or "")[:10] for e in data.get("events") or []}
	return {
		"network": data.get("name", ""),
		"range": f"{data.get('startAddress', '')} – {data.get('endAddress', '')}".strip(" –"),
		"cidr": cidr,
		"country": data.get("country", ""),
		"orgs": orgs[:3],
		"abuse": abuse[:3],
		"contacts": [m for m in contacts if m not in abuse][:3],  # 통신사 담당자 (국내 IP 는 abuse 가 KRNIC 인 경우가 많음)
		"registry": (data.get("port43") or "").replace("whois.", "").replace(".net", "").upper(),
		"registered": events.get("registration", ""),
	}


def ipinfo(ip):
	d = _get_json(f"https://ipinfo.io/{ip}/json")
	asn, _, isp = (d.get("org") or "").partition(" ")
	return {"hostname": d.get("hostname") or "", "city": d.get("city") or "", "region": d.get("region") or "", "country": d.get("country") or "",
			"asn": asn if asn.startswith("AS") else "", "isp": isp if asn.startswith("AS") else d.get("org") or "", "loc": d.get("loc") or ""}


def internetdb(ip):
	try:
		d = _get_json(f"https://internetdb.shodan.io/{ip}")
	except urllib.error.HTTPError as exc:
		if exc.code == 404:
			return {"ports": [], "tags": [], "vulns": [], "hostnames": [], "cpes": []}
		raise
	return {k: d.get(k) or [] for k in ("ports", "tags", "vulns", "hostnames", "cpes")}


def tor_exits():
	hit = cache.get("sec:tor-exits")
	if hit is None:
		req = urllib.request.Request("https://check.torproject.org/torbulkexitlist", headers={"User-Agent": UA})
		with urllib.request.urlopen(req, timeout=8) as res:
			hit = set(res.read().decode().split())
		cache.set("sec:tor-exits", hit, 6 * 60 * 60)
	return hit


def abuseipdb(ip):
	key = getattr(settings, "ABUSEIPDB_API_KEY", "")
	if not key:
		return None
	d = _get_json("https://api.abuseipdb.com/api/v2/check?" + urllib.parse.urlencode({"ipAddress": str(ip), "maxAgeInDays": 90}), {"Key": key})["data"]
	return {"score": d.get("abuseConfidenceScore"), "reports": d.get("totalReports"), "users": d.get("numDistinctUsers"), "last": (d.get("lastReportedAt") or "")[:10], "usage": d.get("usageType") or ""}


def reverse_dns(ip):
	try:
		name = socket.gethostbyaddr(str(ip))[0]
	except OSError:
		return "", False
	try:  # 그 이름이 다시 이 IP 를 가리키는지 (위조된 역방향 이름 거르기)
		confirmed = str(ip) in {a[4][0] for a in socket.getaddrinfo(name, None)}
	except OSError:
		confirmed = False
	return name, confirmed


def external(ip):
	"""외부 공개 정보 (하루 캐시). 실패한 출처는 error 로."""
	key = f"sec:ip:{ip}"
	hit = cache.get(key)
	if hit:
		return hit
	jobs = {"rdap": _pool.submit(rdap, ip), "ipinfo": _pool.submit(ipinfo, ip), "internetdb": _pool.submit(internetdb, ip),
			"tor": _pool.submit(lambda: str(ip) in tor_exits()), "abuseipdb": _pool.submit(abuseipdb, ip), "rdns": _pool.submit(reverse_dns, ip)}
	out, errors = {}, {}
	for name, job in jobs.items():
		try:
			out[name] = job.result(timeout=12)
		except Exception as exc:  # noqa: BLE001 — 출처 하나가 안 돼도 나머지는 보여 줌
			out[name] = None
			errors[name] = str(exc)[:120] or exc.__class__.__name__
	out["errors"] = errors
	out["verdict"] = verdict(out)
	cache.set(key, out, CACHE_SECONDS)
	return out


def verdict(ext):
	"""사람이 읽을 한 줄 판단 + 종류."""
	rdns = (ext.get("rdns") or ("", False))[0]
	info = ext.get("ipinfo") or {}
	rd = ext.get("rdap") or {}
	text = " ".join([rdns, info.get("isp", ""), info.get("hostname", ""), " ".join(rd.get("orgs") or []), rd.get("network", "")]).lower()
	for pattern, label, kind in KNOWN:
		if re.search(pattern, text):
			return {"kind": kind, "label": label}
	if ext.get("tor"):
		return {"kind": "tor", "label": "Tor 출구 노드 (익명 접속)"}
	tags = set((ext.get("internetdb") or {}).get("tags") or [])
	if "vpn" in tags or "proxy" in tags:
		return {"kind": "vpn", "label": "VPN·프록시"}
	if "cloud" in tags or CLOUD.search(text):
		return {"kind": "cloud", "label": "클라우드·호스팅 서버 (사람보다는 프로그램이 접속했을 가능성이 커요)"}
	if (info.get("country") or rd.get("country")) == "KR":
		return {"kind": "isp", "label": "국내 통신사 회선 (가정·사무실·모바일)"}
	return {"kind": "isp", "label": "통신사 회선"}


# ── 우리 서버 기록 ──

def local(ip):
	from blog.models import Comment, GuestbookEntry, Post
	from security.models import IPBlock, LoginEvent

	s = str(ip)
	logins = LoginEvent.objects.filter(ip=s)
	by_result = dict(logins.values_list("result").annotate(n=Count("id")))
	tried = list(logins.exclude(username="").values("username").annotate(n=Count("id")).order_by("-n")[:8])
	first = logins.order_by("created_at").values_list("created_at", flat=True).first()
	last = logins.order_by("-created_at").values_list("created_at", flat=True).first()
	content = {"comment": Comment.objects.filter(author_ip=s).count(), "guestbook": GuestbookEntry.objects.filter(author_ip=s).count(), "post": Post.objects.filter(author_ip=s).count()}
	blocks = [b for b in IPBlock.objects.all() if _covers(b.network, ip)]
	return {
		"logins": {"total": sum(by_result.values()), "by_result": by_result, "tried": tried, "first": first, "last": last, "recent": list(logins.order_by("-created_at")[:8])},
		"content": content,
		"blocks": blocks,
		"access": access_log(s),
		"ssh": ssh_log(s),
	}


def _covers(network, ip):
	try:
		return ip in ipaddress.ip_network(network, strict=False)
	except ValueError:
		return False


ACCESS = re.compile(r'^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] "(?P<method>[A-Z]+) (?P<path>\S+)[^"]*" (?P<status>\d{3}) \S+ "[^"]*" "(?P<ua>[^"]*)"')


def access_log(ip, scan=20000):
	from monitor import logs

	lines, error = logs._read_file("nginx/access.log", scan)
	if lines is None:
		return {"error": error, "hits": 0}
	mine = [m for m in (ACCESS.match(l) for l in lines if l.startswith(ip + " ")) if m]
	status, paths, uas = Counter(), Counter(), Counter()
	for m in mine:
		status[m["status"][0] + "xx"] += 1
		paths[logs.SECRET.sub(r"\1•••", m["path"].split("?")[0])[:80]] += 1
		uas[m["ua"][:120]] += 1
	samples = [logs.SECRET.sub(r"\1•••", m.group(0))[:300] for m in mine[-10:]]
	return {"error": "", "scanned": len(lines), "hits": len(mine), "first": mine[0]["time"] if mine else "", "last": mine[-1]["time"] if mine else "",
			"status": [(k, status.get(k, 0)) for k in ("2xx", "3xx", "4xx", "5xx")], "paths": paths.most_common(8), "uas": uas.most_common(3), "samples": samples}


SSH_USER = re.compile(r"(?:Invalid user|Failed password for(?: invalid user)?) (\S+) from")


def ssh_log(ip, scan=20000):
	from monitor import logs

	lines, error = logs._read_file("auth.log", scan)
	if lines is None:
		return {"error": error, "hits": 0}
	mine = [l for l in lines if re.search(rf"\b{re.escape(ip)}\b", l)]
	fails = [l for l in mine if logs.NOISE.search(l)]
	users = Counter(m.group(1) for m in (SSH_USER.search(l) for l in mine) if m)
	return {"error": "", "hits": len(mine), "fails": len(fails), "accepted": sum(1 for l in mine if "Accepted" in l), "users": users.most_common(8), "samples": mine[-6:]}


def report_text(ip, ext, loc):
	"""abuse 연락처에 보낼 신고 메일 초안 (영어 — 해외 통신사도 읽을 수 있게)."""
	acc, ssh = loc["access"], loc["ssh"]
	lines = [
		f"Hello,",
		"",
		f"We observed unwanted/abusive traffic from {ip} against our server (smjgallery.kr).",
		"",
		f"- HTTP requests: {acc.get('hits', 0)} (first {acc.get('first') or '-'}, last {acc.get('last') or '-'})" if acc.get("hits") else "",
		f"- SSH login failures: {ssh.get('fails', 0)}" if ssh.get("fails") else "",
		f"- Website login failures: {loc['logins']['total'] - loc['logins']['by_result'].get('success', 0)}" if loc["logins"]["total"] else "",
		"",
		"Sample log lines (server time, UTC+9):",
		*(acc.get("samples") or [])[-6:],
		*(ssh.get("samples") or [])[-4:],
		"",
		"Please investigate and take appropriate action. Thank you.",
	]
	return "\n".join(l for l in lines if l is not None).replace("\n\n\n", "\n\n").strip()
